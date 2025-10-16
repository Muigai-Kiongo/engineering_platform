from django import forms
from django.contrib.auth.models import User
from .models import Profile, SupplierProfile, Material, Order, Delivery, SupplierReview, MaterialCategory

# ------- Registration & Profile Forms -------

class UserRegisterForm(forms.ModelForm):
    password = forms.CharField(widget=forms.PasswordInput, label="Password")
    confirm_password = forms.CharField(widget=forms.PasswordInput, label="Confirm Password")
    email = forms.EmailField(required=True, label="Email")

    class Meta:
        model = User
        fields = ['username', 'email', 'password']

    def clean(self):
        cleaned_data = super().clean()
        password = cleaned_data.get('password')
        confirm = cleaned_data.get('confirm_password')
        if password and confirm and password != confirm:
            self.add_error('confirm_password', "Passwords do not match.")
        return cleaned_data

class ProfileForm(forms.ModelForm):
    class Meta:
        model = Profile
        fields = ['role', 'phone', 'address', 'profile_image']
        widgets = {
            'role': forms.Select(attrs={'class': 'form-select'}),
            'phone': forms.TextInput(attrs={'class': 'form-control'}),
            'address': forms.TextInput(attrs={'class': 'form-control'}),
        }

class UserUpdateForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ['username', 'email']

class ProfileUpdateForm(forms.ModelForm):
    class Meta:
        model = Profile
        fields = ['phone', 'address', 'profile_image']

# ------- Supplier Forms -------

class SupplierProfileForm(forms.ModelForm):
    class Meta:
        model = SupplierProfile
        fields = ['company_name', 'description', 'verified']
        widgets = {
            'company_name': forms.TextInput(attrs={'class': 'form-control'}),
            'description': forms.Textarea(attrs={'rows': 3, 'class': 'form-control'}),
        }

# ------- Material Forms -------

class MaterialForm(forms.ModelForm):
    class Meta:
        model = Material
        fields = ['name', 'category', 'description', 'unit_price', 'stock_level', 'image', 'is_active']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'category': forms.TextInput(attrs={'class': 'form-control'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
            'unit_price': forms.NumberInput(attrs={'class': 'form-control'}),
            'stock_level': forms.NumberInput(attrs={'class': 'form-control'}),
        }

class MaterialCategoryForm(forms.ModelForm):
    class Meta:
        model = MaterialCategory
        fields = ['name', 'description']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'description': forms.Textarea(attrs={'rows': 2, 'class': 'form-control'}),
        }

# ------- Order Forms -------

class OrderForm(forms.ModelForm):
    class Meta:
        model = Order
        fields = ['material', 'quantity']
        widgets = {
            'material': forms.Select(attrs={'class': 'form-select'}),
            'quantity': forms.NumberInput(attrs={'class': 'form-control'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['material'].queryset = Material.objects.filter(is_active=True)

    def clean_quantity(self):
        quantity = self.cleaned_data['quantity']
        material = self.cleaned_data.get('material')
        if material:
            if quantity > material.stock_level:
                raise forms.ValidationError("Ordered quantity exceeds available stock.")
        if quantity <= 0:
            raise forms.ValidationError("Quantity must be greater than zero.")
        return quantity

# ------- Delivery Forms -------

class DeliveryForm(forms.ModelForm):
    class Meta:
        model = Delivery
        fields = ['delivery_location', 'dispatched_at', 'delivered_at', 'delivery_agent', 'notes']
        widgets = {
            'delivery_location': forms.TextInput(attrs={'class': 'form-control'}),
            'dispatched_at': forms.DateTimeInput(attrs={'type': 'datetime-local', 'class': 'form-control'}),
            'delivered_at': forms.DateTimeInput(attrs={'type': 'datetime-local', 'class': 'form-control'}),
            'notes': forms.Textarea(attrs={'rows': 2, 'class': 'form-control'}),
        }

# ------- Review Forms -------

class SupplierReviewForm(forms.ModelForm):
    class Meta:
        model = SupplierReview
        fields = ['rating', 'feedback']
        widgets = {
            'rating': forms.NumberInput(attrs={'class': 'form-control', 'min': 1, 'max': 5}),
            'feedback': forms.Textarea(attrs={'rows': 2, 'class': 'form-control'}),
        }

    def clean_rating(self):
        rating = self.cleaned_data['rating']
        if rating < 1 or rating > 5:
            raise forms.ValidationError("Rating must be between 1 and 5.")
        return rating