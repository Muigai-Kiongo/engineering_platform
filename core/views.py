from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Q, Avg
from .models import (
    Material, Order, Profile, SupplierReview, SupplierProfile, MaterialCategory
)
from .forms import OrderForm, SupplierReviewForm, MaterialForm

# --------- Unified Role Helpers ---------
def get_user_role(user):
    """Safely get the user's role, or None if not set."""
    if hasattr(user, 'profile'):
        return getattr(user.profile, "role", None)
    return None

def is_engineer(user):
    return get_user_role(user) == 'engineer'

def is_supplier(user):
    return get_user_role(user) == 'supplier'

def engineer_only(view_func):
    """Decorator: Only allow engineer users."""
    def _wrapped(request, *args, **kwargs):
        if not is_engineer(request.user):
            messages.error(request, "Access denied: Engineers only.")
            return redirect('login')
        return view_func(request, *args, **kwargs)
    return login_required(_wrapped)

def supplier_only(view_func):
    """Decorator: Only allow supplier users."""
    def _wrapped(request, *args, **kwargs):
        if not is_supplier(request.user):
            messages.error(request, "Access denied: Suppliers only.")
            return redirect('login')
        return view_func(request, *args, **kwargs)
    return login_required(_wrapped)


@login_required
def role_redirect(request):
    """Redirect to appropriate page based on user role."""
    if is_engineer(request.user):
        return redirect('engineer_dashboard')
    elif is_supplier(request.user):
        return redirect('supplier_dashboard')
    else:
        return redirect('login')


# --------- Engineer Views ---------
@engineer_only
def engineer_dashboard(request):
    """Engineer dashboard with recent orders."""
    orders = request.user.profile.orders.select_related('material', 'supplier').order_by('-created_at')
    return render(request, 'engineers/engineer_dashboard.html', {'orders': orders})

@engineer_only
def material_list(request):
    """List all active materials for engineers."""
    query = request.GET.get('q', '')
    category = request.GET.get('category', '')
    materials = Material.objects.filter(is_active=True, stock_level__gt=0)
    categories = MaterialCategory.objects.all()
    if query:
        materials = materials.filter(
            Q(name__icontains=query) | Q(description__icontains=query) | Q(supplier__company_name__icontains=query)
        )
    if category:
        materials = materials.filter(category__iexact=category)
    return render(request, 'engineers/material_list.html', {
        'materials': materials,
        'categories': categories,
        'query': query,
        'selected_category': category,
    })

@engineer_only
def material_detail(request, pk):
    """Material detail for engineers."""
    material = get_object_or_404(Material, pk=pk, is_active=True)
    supplier = material.supplier
    reviews = supplier.reviews.all().order_by('-created_at')[:5]
    return render(request, 'engineers/material_detail.html', {
        'material': material,
        'supplier': supplier,
        'reviews': reviews,
    })

@engineer_only
def place_order(request, material_id):
    """Engineers place an order for a material."""
    material = get_object_or_404(Material, pk=material_id, is_active=True)
    supplier = material.supplier
    if request.method == 'POST':
        form = OrderForm(request.POST)
        form.fields['material'].queryset = Material.objects.filter(pk=material_id)
        if form.is_valid():
            order = form.save(commit=False)
            order.engineer = request.user.profile
            order.supplier = supplier
            order.material = material
            order.total_price = material.unit_price * order.quantity
            order.save()
            messages.success(request, f"Order placed for {material.name}.")
            return redirect('engineer_dashboard')
    else:
        form = OrderForm(initial={'material': material})
        form.fields['material'].queryset = Material.objects.filter(pk=material_id)
    return render(request, 'engineers/place_order.html', {
        'material': material,
        'form': form,
        'supplier': supplier,
    })

@engineer_only
def order_list(request):
    """Show engineer's order history."""
    orders = request.user.profile.orders.select_related('material', 'supplier').order_by('-created_at')
    return render(request, 'engineers/order_list.html', {'orders': orders})

@engineer_only
def order_detail(request, order_id):
    """Engineers view their order detail."""
    order = get_object_or_404(Order, pk=order_id, engineer=request.user.profile)
    return render(request, 'engineers/order_detail.html', {'order': order})

@engineer_only
def review_supplier(request, supplier_id):
    """Engineer reviews a supplier."""
    supplier = get_object_or_404(SupplierProfile, pk=supplier_id)
    if request.method == 'POST':
        form = SupplierReviewForm(request.POST)
        if form.is_valid():
            review = form.save(commit=False)
            review.engineer = request.user.profile
            review.supplier = supplier
            review.save()
            messages.success(request, "Review submitted.")
            return redirect('material_list')
    else:
        form = SupplierReviewForm()
    return render(request, 'engineers/review_supplier.html', {
        'form': form,
        'supplier': supplier,
    })

# --------- Supplier Views ---------
@supplier_only
def supplier_dashboard(request):
    """Supplier dashboard with recent orders and stats."""
    supplier_profile = SupplierProfile.objects.filter(profile=request.user.profile).first()
    if not supplier_profile:
        messages.error(request, "No supplier profile found. Please contact support.")
        return redirect('login')
    recent_orders = Order.objects.filter(supplier=supplier_profile).order_by('-created_at')[:5]
    materials = Material.objects.filter(supplier=supplier_profile)
    reviews = SupplierReview.objects.filter(supplier=supplier_profile)
    avg_rating = reviews.aggregate(Avg('rating'))['rating__avg'] or 0
    return render(request, "supplier/supplier_dashboard.html", {
        "supplier": supplier_profile,
        "recent_orders": recent_orders,
        "materials": materials,
        "reviews": reviews,
        "avg_rating": round(avg_rating, 2),
    })

@supplier_only
def supplier_orders(request):
    """Supplier's received orders."""
    supplier_profile = SupplierProfile.objects.filter(profile=request.user.profile).first()
    if not supplier_profile:
        messages.error(request, "No supplier profile found. Please contact support.")
        return redirect('login')
    orders = Order.objects.filter(supplier=supplier_profile).order_by('-created_at')
    return render(request, "supplier/supplier_orders.html", {"orders": orders})

@supplier_only
def supplier_materials(request):
    """Supplier's materials list."""
    supplier_profile = SupplierProfile.objects.filter(profile=request.user.profile).first()
    if not supplier_profile:
        messages.error(request, "No supplier profile found. Please contact support.")
        return redirect('login')
    materials = Material.objects.filter(supplier=supplier_profile)
    return render(request, "supplier/supplier_materials.html", {"materials": materials})


@supplier_only
def supplier_add_material(request):
    supplier_profile = SupplierProfile.objects.filter(profile=request.user.profile).first()
    if not supplier_profile:
        messages.error(request, "No supplier profile found. Please contact support.")
        return redirect('login')
    if request.method == 'POST':
        form = MaterialForm(request.POST, request.FILES)
        if form.is_valid():
            material = form.save(commit=False)
            material.supplier = supplier_profile
            material.save()
            messages.success(request, f"Material '{material.name}' added successfully.")
            return redirect('supplier_materials')
    else:
        form = MaterialForm()
    return render(request, 'supplier/supplier_add_material.html', {'form': form})


@supplier_only
def supplier_material_detail(request, pk):
    """Supplier's material detail and orders for that material."""
    supplier_profile = SupplierProfile.objects.filter(profile=request.user.profile).first()
    if not supplier_profile:
        messages.error(request, "No supplier profile found. Please contact support.")
        return redirect('login')
    material = get_object_or_404(Material, pk=pk, supplier=supplier_profile)
    orders = Order.objects.filter(material=material)
    return render(request, "supplier/supplier_material_detail.html", {"material": material, "orders": orders})

@supplier_only
def supplier_profile(request):
    """Supplier's profile page."""
    supplier_profile = SupplierProfile.objects.filter(profile=request.user.profile).first()
    if not supplier_profile:
        messages.error(request, "No supplier profile found. Please contact support.")
        return redirect('login')
    # Profile form logic goes here...
    return render(request, "supplier/supplier_profile.html", {"supplier": supplier_profile})

@supplier_only
def supplier_reviews(request):
    """Supplier's reviews page."""
    supplier_profile = SupplierProfile.objects.filter(profile=request.user.profile).first()
    if not supplier_profile:
        messages.error(request, "No supplier profile found. Please contact support.")
        return redirect('login')
    reviews = SupplierReview.objects.filter(supplier=supplier_profile)
    return render(request, "supplier/supplier_reviews.html", {"reviews": reviews, "supplier": supplier_profile})