from django.db import models
from django.contrib.auth.models import User

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
    profile = models.OneToOneField(Profile, on_delete=models.CASCADE, limit_choices_to={'role': 'supplier'}, related_name='supplier_profile')
    company_name = models.CharField(max_length=255)
    verified = models.BooleanField(default=False)
    rating = models.FloatField(default=0)
    registration_date = models.DateField(auto_now_add=True)
    description = models.TextField(blank=True)
    def __str__(self):
        return self.company_name

# Material/Inventory Item
class Material(models.Model):
    supplier = models.ForeignKey(SupplierProfile, on_delete=models.CASCADE, related_name="materials")
    name = models.CharField(max_length=255)
    category = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    unit_price = models.DecimalField(max_digits=10, decimal_places=2)
    stock_level = models.PositiveIntegerField(default=0)
    image = models.ImageField(upload_to='materials/', blank=True, null=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    def __str__(self):
        return f"{self.name} ({self.supplier.company_name})"

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
    quantity = models.PositiveIntegerField()
    total_price = models.DecimalField(max_digits=12, decimal_places=2)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    invoice_file = models.FileField(upload_to='invoices/', blank=True, null=True)
    def __str__(self):
        return f"Order #{self.id} by {self.engineer.user.username}"

# Delivery Model
class Delivery(models.Model):
    order = models.OneToOneField(Order, on_delete=models.CASCADE, related_name='delivery')
    dispatched_at = models.DateTimeField(null=True, blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)
    delivery_location = models.CharField(max_length=255)
    delivery_agent = models.ForeignKey(Profile, on_delete=models.SET_NULL, null=True, blank=True, limit_choices_to={'role': 'delivery'}, related_name='deliveries')
    notes = models.TextField(blank=True)
    def __str__(self):
        return f"Delivery for Order #{self.order.id}"

# Supplier Reviews
class SupplierReview(models.Model):
    engineer = models.ForeignKey(Profile, on_delete=models.CASCADE, limit_choices_to={'role': 'engineer'})
    supplier = models.ForeignKey(SupplierProfile, on_delete=models.CASCADE, related_name='reviews')
    rating = models.PositiveSmallIntegerField()
    feedback = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    def __str__(self):
        return f"Review by {self.engineer.user.username} for {self.supplier.company_name}"

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

# Optional: Material Category for better search/filtering
class MaterialCategory(models.Model):
    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True)
    def __str__(self):
        return self.name