from django.db import models
from django.contrib.auth.models import User
from django.core.validators import MinValueValidator, MaxValueValidator
from django.utils.text import slugify
from django.db.models.signals import pre_save
from django.dispatch import receiver

# Extended Profile for all users (Engineer, Supplier, Admin, Delivery Agent)
class Profile(models.Model):
    ROLE_CHOICES = (
        ('engineer', 'Engineer'),
        ('supplier', 'Supplier'),
        ('admin', 'Administrator'),
        ('delivery', 'Delivery Agent'),
    )
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    role = models.CharField(max_length=20, choices=ROLE_CHOICES)
    phone = models.CharField(max_length=20, blank=True)
    address = models.CharField(max_length=255, blank=True)
    profile_image = models.ImageField(upload_to='profile_images/', blank=True, null=True)

    def __str__(self):
        return f"{self.user.username} ({self.role})"


# Supplier-specific profile
class SupplierProfile(models.Model):
    profile = models.OneToOneField(
        Profile,
        on_delete=models.CASCADE,
        limit_choices_to={'role': 'supplier'},
        related_name='supplier_profile'
    )
    company_name = models.CharField(max_length=255)
    verified = models.BooleanField(default=False)
    # Keep rating bounded between 0 and 5
    rating = models.DecimalField(max_digits=3, decimal_places=2, default=0,
                                 validators=[MinValueValidator(0), MaxValueValidator(5)])
    registration_date = models.DateField(auto_now_add=True)
    description = models.TextField(blank=True)

    def __str__(self):
        return self.company_name

    def update_rating_from_reviews(self):
        reviews = self.reviews.all()
        if not reviews.exists():
            self.rating = 0
        else:
            avg = reviews.aggregate(models.Avg('rating'))['rating__avg'] or 0
            self.rating = round(avg, 2)
        self.save(update_fields=['rating'])


# Material Category for better search/filtering and hierarchical categorization
class MaterialCategory(models.Model):
    name = models.CharField(max_length=100)
    slug = models.SlugField(max_length=120, unique=True, blank=True)
    parent = models.ForeignKey('self', null=True, blank=True, related_name='children', on_delete=models.SET_NULL)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('parent', 'name')
        ordering = ['parent__id', 'name']

    def __str__(self):
        return self.name

    def full_path(self):
        parts = [self.name]
        ancestor = self.parent
        while ancestor:
            parts.append(ancestor.name)
            ancestor = ancestor.parent
        return " > ".join(reversed(parts))


@receiver(pre_save, sender=MaterialCategory)
def material_category_pre_save(sender, instance, **kwargs):
    if not instance.slug:
        base = slugify(instance.name)[:100]
        slug = base
        counter = 1
        while MaterialCategory.objects.filter(slug=slug).exclude(pk=instance.pk).exists():
            slug = f"{base}-{counter}"
            counter += 1
        instance.slug = slug


# Custom manager for Material
class MaterialManager(models.Manager):
    def active(self):
        return self.filter(is_active=True, stock_level__gt=0)


# Material/Inventory Item
class Material(models.Model):
    supplier = models.ForeignKey(SupplierProfile, on_delete=models.CASCADE, related_name="materials")
    name = models.CharField(max_length=255)
    sku = models.CharField(max_length=64, blank=True, help_text="Optional supplier SKU")
    # Primary category for default grouping
    primary_category = models.ForeignKey(
        MaterialCategory, null=True, blank=True, on_delete=models.SET_NULL, related_name='primary_materials'
    )
    # Allow multiple categories for flexible tagging/filtering
    categories = models.ManyToManyField(MaterialCategory, blank=True, related_name='materials')
    description = models.TextField(blank=True)
    unit = models.CharField(max_length=50, default='unit', help_text='Unit of measurement (e.g., pcs, m, kg)')
    unit_price = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(0)])
    stock_level = models.PositiveIntegerField(default=0)
    image = models.ImageField(upload_to='materials/', blank=True, null=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    objects = MaterialManager()

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['name']),
            models.Index(fields=['sku']),
        ]
        unique_together = (('supplier', 'sku'),)  # ensure per-supplier SKU uniqueness (if SKU provided)

    def __str__(self):
        return f"{self.name} ({self.supplier.company_name})"

    @property
    def available(self):
        return self.is_active and self.stock_level > 0

    def adjust_stock(self, delta):
        """Adjust stock by delta (positive or negative). Returns new stock level."""
        if delta < 0 and abs(delta) > self.stock_level:
            raise ValueError("Not enough stock to decrement by requested amount.")
        self.stock_level = models.F('stock_level') + delta
        self.save(update_fields=['stock_level'])
        # refresh from db to get actual value
        self.refresh_from_db(fields=['stock_level'])
        return self.stock_level


# Order Model
class Order(models.Model):
    STATUS_CHOICES = (
        ('pending', 'Pending'),
        ('confirmed', 'Confirmed'),
        ('dispatched', 'Dispatched'),
        ('delivered', 'Delivered'),
        ('cancelled', 'Cancelled'),
    )
    engineer = models.ForeignKey(Profile, on_delete=models.CASCADE, limit_choices_to={'role': 'engineer'}, related_name='orders')
    supplier = models.ForeignKey(SupplierProfile, on_delete=models.CASCADE, related_name='orders')
    material = models.ForeignKey(Material, on_delete=models.CASCADE)
    quantity = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    total_price = models.DecimalField(max_digits=12, decimal_places=2)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    invoice_file = models.FileField(upload_to='invoices/', blank=True, null=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"Order #{self.id} by {self.engineer.user.username}"

    def save(self, *args, **kwargs):
        # Auto-calculate total_price if not set or if material/unit_price changed
        if not self.total_price:
            self.total_price = (self.material.unit_price or 0) * self.quantity
        super().save(*args, **kwargs)


# Delivery Model
class Delivery(models.Model):
    order = models.OneToOneField(Order, on_delete=models.CASCADE, related_name='delivery')
    dispatched_at = models.DateTimeField(null=True, blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)
    delivery_location = models.CharField(max_length=255)
    delivery_agent = models.ForeignKey(
        Profile, on_delete=models.SET_NULL, null=True, blank=True,
        limit_choices_to={'role': 'delivery'}, related_name='deliveries'
    )
    notes = models.TextField(blank=True)

    def __str__(self):
        return f"Delivery for Order #{self.order.id}"


# Supplier Reviews
class SupplierReview(models.Model):
    engineer = models.ForeignKey(Profile, on_delete=models.CASCADE, limit_choices_to={'role': 'engineer'})
    supplier = models.ForeignKey(SupplierProfile, on_delete=models.CASCADE, related_name='reviews')
    rating = models.PositiveSmallIntegerField(validators=[MinValueValidator(1), MaxValueValidator(5)])
    feedback = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        # optionally enforce one review per engineer per supplier:
        # unique_together = ('engineer', 'supplier')

    def __str__(self):
        return f"Review by {self.engineer.user.username} for {self.supplier.company_name}"


@receiver(models.signals.post_save, sender=SupplierReview)
def update_supplier_rating_on_review(sender, instance, **kwargs):
    try:
        instance.supplier.update_rating_from_reviews()
    except Exception:
        # ensure reviews don't crash main flow; consider logging in production
        pass


# Audit Log for admin tracking
class AuditLog(models.Model):
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    action = models.CharField(max_length=255)
    timestamp = models.DateTimeField(auto_now_add=True)
    details = models.TextField(blank=True)

    def __str__(self):
        return f"{self.action} by {self.user.username if self.user else 'Unknown'} @ {self.timestamp}"


# Optional: Notification system
class Notification(models.Model):
    recipient = models.ForeignKey(Profile, on_delete=models.CASCADE, related_name='notifications')
    message = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)
    is_read = models.BooleanField(default=False)
    link = models.URLField(blank=True)

    def __str__(self):
        return f"Notification to {self.recipient.user.username}"