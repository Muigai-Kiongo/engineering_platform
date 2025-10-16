from django.shortcuts import render, redirect
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.forms import AuthenticationForm
from django.db import transaction
from django.contrib.auth.decorators import login_required
from core.forms import UserRegisterForm, ProfileForm
from core.models import Profile, SupplierProfile

def get_user_role(user):
    """Safely get the user's role, or None if not set."""
    if hasattr(user, 'profile'):
        return getattr(user.profile, "role", None)
    return None

def login_view(request):
    if request.user.is_authenticated:
        role = get_user_role(request.user)
        if role == 'engineer':
            return redirect('engineer_dashboard')
        elif role == 'supplier':
            return redirect('supplier_dashboard')
        elif role == 'admin':
            return redirect('/admin/')
        else:
            return redirect('/')
    form = AuthenticationForm(request, data=request.POST or None)
    if request.method == 'POST':
        if form.is_valid():
            user = form.get_user()
            login(request, user)
            messages.success(request, f"Welcome, {user.username}!")
            role = get_user_role(user)
            if role == 'engineer':
                return redirect('engineer_dashboard')
            elif role == 'supplier':
                return redirect('supplier_dashboard')
            elif role == 'admin':
                return redirect('/admin/')
            else:
                return redirect('/')
        else:
            messages.error(request, "Invalid login credentials.")
    return render(request, 'registration/login.html', {'form': form})

def register_view(request):
    if request.user.is_authenticated:
        role = get_user_role(request.user)
        if role == 'engineer':
            return redirect('engineer_dashboard')
        elif role == 'supplier':
            return redirect('supplier_dashboard')
        elif role == 'admin':
            return redirect('/admin/')
        else:
            return redirect('/')
    if request.method == 'POST':
        user_form = UserRegisterForm(request.POST)
        profile_form = ProfileForm(request.POST, request.FILES)
        if user_form.is_valid() and profile_form.is_valid():
            with transaction.atomic():
                # Create user
                user = user_form.save(commit=False)
                user.set_password(user_form.cleaned_data['password'])
                user.save()
                # Create profile
                profile = profile_form.save(commit=False)
                profile.user = user
                profile.save()
                # If registering as supplier, create SupplierProfile
                if profile.role == 'supplier':
                    SupplierProfile.objects.create(
                        profile=profile,
                        company_name=profile_form.cleaned_data.get('company_name', '')
                    )
            messages.success(request, "Account created successfully. Please log in.")
            return redirect('login')
        else:
            messages.error(request, "Please correct the errors below.")
    else:
        user_form = UserRegisterForm()
        profile_form = ProfileForm()
    return render(request, 'registration/register.html', {
        'form': user_form,
        'profile_form': profile_form,
    })

@login_required
def my_account_view(request):
    profile = getattr(request.user, 'profile', None)
    supplier_profile = None
    if profile and profile.role == "supplier":
        supplier_profile = getattr(profile, 'supplierprofile', None)
    context = {
        'profile': profile,
        'supplier_profile': supplier_profile,
    }
    return render(request, 'accounts/my_account.html', context)