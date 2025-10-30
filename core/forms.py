from typing import Optional

from django import forms
from django.contrib.auth.models import User
from django.forms import HiddenInput
from django.core.exceptions import ValidationError

from .models import (
    Profile,
    SupplierProfile,
    Material,
    Order,
    Delivery,
    SupplierReview,
    MaterialCategory,
)


# ------- Registration & Profile Forms -------
class UserRegisterForm(forms.ModelForm):
    password = forms.CharField(widget=forms.PasswordInput, label="Password")
    confirm_password = forms.CharField(widget=forms.PasswordInput, label="Confirm Password")
    email = forms.EmailField(required=True, label="Email")

    class Meta:
        model = User
        fields = ["username", "email", "password"]

    def clean(self):
        cleaned_data = super().clean()
        password = cleaned_data.get("password")
        confirm = cleaned_data.get("confirm_password")
        if password and confirm and password != confirm:
            self.add_error("confirm_password", "Passwords do not match.")
        return cleaned_data

    def clean_email(self):
        email = self.cleaned_data.get("email")
        if email and User.objects.filter(email__iexact=email).exists():
            raise ValidationError("A user with that email already exists.")
        return email


class ProfileForm(forms.ModelForm):
    class Meta:
        model = Profile
        fields = ["role", "phone", "address", "profile_image"]
        widgets = {
            "role": forms.Select(attrs={"class": "form-select"}),
            "phone": forms.TextInput(attrs={"class": "form-control"}),
            "address": forms.TextInput(attrs={"class": "form-control"}),
        }


class UserUpdateForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ["username", "email"]


class ProfileUpdateForm(forms.ModelForm):
    class Meta:
        model = Profile
        fields = ["phone", "address", "profile_image"]


# ------- Supplier Forms -------
class SupplierProfileForm(forms.ModelForm):
    class Meta:
        model = SupplierProfile
        fields = ["company_name", "description", "verified"]
        widgets = {
            "company_name": forms.TextInput(attrs={"class": "form-control"}),
            "description": forms.Textarea(attrs={"rows": 3, "class": "form-control"}),
        }


# ------- Material Category Form -------
class MaterialCategoryForm(forms.ModelForm):
    parent = forms.ModelChoiceField(
        queryset=MaterialCategory.objects.all(), required=False, widget=forms.Select(attrs={"class": "form-select"})
    )

    class Meta:
        model = MaterialCategory
        fields = ["name", "parent", "description", "is_active"]
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-control"}),
            "description": forms.Textarea(attrs={"rows": 2, "class": "form-control"}),
            "is_active": forms.CheckboxInput(),
        }


# ------- Material Forms -------
class MaterialForm(forms.ModelForm):
    """
    Enhanced Material form:
    - supports selecting multiple categories (M2M)
    - supports selecting a primary_category (optional)
    - validates per-supplier SKU uniqueness if supplier is provided to the form
    - optionally accepts `supplier` and `instance` when initializing so the form can be used
      both for create and update workflows.
    """

    categories = forms.ModelMultipleChoiceField(
        queryset=MaterialCategory.objects.filter(is_active=True),
        required=False,
        widget=forms.SelectMultiple(attrs={"class": "form-control"}),
        help_text="Assign one or more categories",
    )
    primary_category = forms.ModelChoiceField(
        queryset=MaterialCategory.objects.filter(is_active=True),
        required=False,
        widget=forms.Select(attrs={"class": "form-select"}),
        help_text="Optional primary category (recommended to be one of the selected categories)",
    )
    sku = forms.CharField(required=False, widget=forms.TextInput(attrs={"class": "form-control"}))
    unit = forms.CharField(required=False, widget=forms.TextInput(attrs={"class": "form-control"}))

    class Meta:
        model = Material
        fields = [
            "name",
            "sku",
            "unit",
            "primary_category",
            "categories",
            "description",
            "unit_price",
            "stock_level",
            "image",
            "is_active",
        ]
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-control"}),
            "description": forms.Textarea(attrs={"class": "form-control", "rows": 2}),
            "unit_price": forms.NumberInput(attrs={"class": "form-control", "min": 0}),
            "stock_level": forms.NumberInput(attrs={"class": "form-control", "min": 0}),
            "image": forms.ClearableFileInput(attrs={"class": "form-control-file"}),
            "is_active": forms.CheckboxInput(),
        }

    def __init__(self, *args, supplier: Optional[SupplierProfile] = None, **kwargs):
        """
        Accept optional `supplier` parameter so we can validate SKU uniqueness and
        set the supplier on save for create workflows.
        """
        self._supplier = supplier
        super().__init__(*args, **kwargs)

        # If editing an existing Material instance, pre-populate categories
        if self.instance and self.instance.pk:
            self.fields["categories"].initial = self.instance.categories.all()
            if self.instance.primary_category:
                self.fields["primary_category"].initial = self.instance.primary_category

        # When supplier is provided, show a hint and keep SKU validation aware of it
        if supplier:
            self.fields["sku"].help_text = "Optional SKU unique for the supplier: %s" % supplier.company_name

    def clean_sku(self):
        sku = self.cleaned_data.get("sku", "").strip()
        if not sku:
            return sku

        supplier = self._supplier or getattr(self.instance, "supplier", None)
        if not supplier:
            # If we don't know supplier context, skip uniqueness enforcement here;
            # views should ensure supplier is set or pass supplier to the form.
            return sku

        qs = Material.objects.filter(supplier=supplier, sku__iexact=sku)
        if self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise ValidationError("This SKU is already in use for the selected supplier.")
        return sku

    def clean(self):
        cleaned = super().clean()
        primary = cleaned.get("primary_category")
        categories = cleaned.get("categories")
        if primary and categories and primary not in categories:
            # Not strictly required, but it's helpful to guide users to include primary in categories
            self.add_error(
                "primary_category",
                "Primary category should normally be one of the selected categories. Either add it to categories or clear the primary category.",
            )
        return cleaned

    def save(self, commit=True):
        # Ensure supplier is set on create if passed to the form
        instance = super().save(commit=False)
        if not getattr(instance, "supplier", None) and self._supplier:
            instance.supplier = self._supplier
        if commit:
            instance.save()
            # m2m must be set after initial save
            if "categories" in self.cleaned_data:
                instance.categories.set(self.cleaned_data["categories"])
            else:
                # If form didn't include categories, don't modify existing ones on update
                if not self.instance.pk:
                    instance.categories.clear()
            # keep primary_category set by the ModelForm save
            # ensure stock_level and unit_price are properly stored (handled by model validators)
        return instance


# ------- Order Forms -------
class OrderForm(forms.ModelForm):
    """
    If `material` is provided to __init__, the material field will be restricted to that instance
    and will use a HiddenInput so clients cannot change it.
    """

    class Meta:
        model = Order
        fields = ["material", "quantity"]
        widgets = {
            "material": forms.Select(attrs={"class": "form-select"}),
            "quantity": forms.NumberInput(attrs={"class": "form-control", "min": 1}),
        }

    def __init__(self, *args, material: Optional[Material] = None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["material"].queryset = Material.objects.filter(is_active=True)
        self.locked_material = None
        if material is not None:
            self.locked_material = material
            self.fields["material"].queryset = Material.objects.filter(pk=material.pk)
            self.fields["material"].initial = material.pk
            self.fields["material"].widget = HiddenInput()

    def clean_quantity(self):
        quantity = self.cleaned_data.get("quantity")
        # determine the material to check stock against
        material = None
        if "material" in self.cleaned_data and self.cleaned_data["material"]:
            material = self.cleaned_data["material"]
        else:
            material = self.locked_material

        if quantity is None or quantity <= 0:
            raise ValidationError("Quantity must be greater than zero.")

        if material:
            if quantity > material.stock_level:
                raise ValidationError("Ordered quantity exceeds available stock.")
        return quantity

    def save(self, commit=True):
        """
        Ensure total_price is calculated from material.unit_price * quantity if not provided.
        Other fields like engineer/supplier should be set in the view before saving if needed.
        """
        instance = super().save(commit=False)
        # compute total price from current material price
        price = getattr(instance.material, "unit_price", None) or 0
        instance.total_price = price * instance.quantity
        if commit:
            instance.save()
        return instance


# ------- Delivery Forms -------
class DeliveryForm(forms.ModelForm):
    class Meta:
        model = Delivery
        fields = ["delivery_location", "dispatched_at", "delivered_at", "delivery_agent", "notes"]
        widgets = {
            "delivery_location": forms.TextInput(attrs={"class": "form-control"}),
            "dispatched_at": forms.DateTimeInput(attrs={"type": "datetime-local", "class": "form-control"}),
            "delivered_at": forms.DateTimeInput(attrs={"type": "datetime-local", "class": "form-control"}),
            "notes": forms.Textarea(attrs={"rows": 2, "class": "form-control"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # limit delivery_agent to Profiles with role 'delivery'
        self.fields["delivery_agent"].queryset = Profile.objects.filter(role="delivery")


# ------- Review Forms -------
class SupplierReviewForm(forms.ModelForm):
    class Meta:
        model = SupplierReview
        fields = ["rating", "feedback"]
        widgets = {
            "rating": forms.NumberInput(attrs={"class": "form-control", "min": 1, "max": 5}),
            "feedback": forms.Textarea(attrs={"rows": 2, "class": "form-control"}),
        }

    def clean_rating(self):
        rating = self.cleaned_data["rating"]
        if rating < 1 or rating > 5:
            raise ValidationError("Rating must be between 1 and 5.")
        return rating