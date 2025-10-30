from typing import Optional

from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Q, Avg, Sum, Count
from django.core.exceptions import FieldDoesNotExist
from django.views.decorators.http import require_POST
from django.conf import settings
from django.http import HttpResponseForbidden, JsonResponse
from django.utils import timezone
import logging

from .models import (
    Material,
    Order,
    Profile,
    SupplierReview,
    SupplierProfile,
    MaterialCategory,
    Delivery,
)
from .forms import OrderForm, SupplierReviewForm, MaterialForm

# Email helpers (must exist at core/email_utils.py)
from .email_utils import send_order_placed, send_order_dispatched, send_order_delivered

logger = logging.getLogger(__name__)


# --------- Unified Role Helpers ---------
def get_user_role(user):
    """Safely get the user's role, or None if not set."""
    if hasattr(user, "profile"):
        return getattr(user.profile, "role", None)
    return None


def is_engineer(user):
    return get_user_role(user) == "engineer"


def is_supplier(user):
    return get_user_role(user) == "supplier"


def is_delivery(user):
    return get_user_role(user) == "delivery"


def engineer_only(view_func):
    """Decorator: Only allow engineer users."""

    def _wrapped(request, *args, **kwargs):
        if not is_engineer(request.user):
            messages.error(request, "Access denied: Engineers only.")
            return redirect("login")
        return view_func(request, *args, **kwargs)

    return login_required(_wrapped)


def supplier_only(view_func):
    """Decorator: Only allow supplier users."""

    def _wrapped(request, *args, **kwargs):
        if not is_supplier(request.user):
            messages.error(request, "Access denied: Suppliers only.")
            return redirect("login")
        return view_func(request, *args, **kwargs)

    return login_required(_wrapped)


def delivery_only(view_func):
    """Decorator: Only allow delivery-agent users."""

    def _wrapped(request, *args, **kwargs):
        if not is_delivery(request.user):
            messages.error(request, "Access denied: Delivery agents only.")
            return redirect("login")
        return view_func(request, *args, **kwargs)

    return login_required(_wrapped)


@login_required
def role_redirect(request):
    """Redirect to appropriate page based on user role."""
    if is_engineer(request.user):
        return redirect("engineer_dashboard")
    elif is_supplier(request.user):
        return redirect("supplier_dashboard")
    elif is_delivery(request.user):
        return redirect("delivery_dashboard")
    else:
        return redirect("login")


# --------- Helpers ---------
def assign_delivery_agent(order):
    """
    Find a delivery agent with the least active load and create a Delivery record linked to `order`.
    Safe/fails gracefully if Delivery/Profile models or fields differ.
    """
    try:
        # If a delivery already exists for this order, return it
        existing = Delivery.objects.filter(order=order).first()
    except Exception:
        return None
    if existing:
        return existing

    # Find active delivery agent profiles
    try:
        agents_qs = Profile.objects.filter(role="delivery", user__is_active=True)
    except Exception:
        return None

    if not agents_qs.exists():
        return None

    # Count active deliveries per agent (not yet delivered)
    try:
        counts_qs = (
            Delivery.objects.filter(delivery_agent__in=agents_qs, delivered_at__isnull=True)
            .values("delivery_agent")
            .annotate(active_count=Count("id"))
        )
        counts_map = {entry["delivery_agent"]: entry["active_count"] for entry in counts_qs}
    except Exception:
        counts_map = {}

    # Choose the agent with minimum active_count
    selected = None
    min_count = None
    for agent in agents_qs:
        cnt = counts_map.get(agent.id, 0)
        if min_count is None or cnt < min_count:
            min_count = cnt
            selected = agent

    if selected is None:
        return None

    # Determine delivery_location from order if available
    delivery_location = ""
    if hasattr(order, "delivery_location") and getattr(order, "delivery_location"):
        delivery_location = order.delivery_location
    elif hasattr(order, "shipping_address") and getattr(order, "shipping_address"):
        delivery_location = order.shipping_address
    elif hasattr(order, "supplier") and getattr(order.supplier, "profile", None):
        supplier_profile = order.supplier.profile
        delivery_location = getattr(supplier_profile, "address", "") or ""

    # Create the Delivery record safely
    try:
        delivery = Delivery.objects.create(
            order=order, delivery_agent=selected, delivery_location=delivery_location
        )
        return delivery
    except Exception as exc:
        logger.exception(
            "Failed to create Delivery for Order %s: %s", getattr(order, "id", None), exc
        )
        return None


@login_required
def notifications(request):
    """
    Defensive notifications view. Tries profile.notifications then user.notifications.
    """
    user = request.user
    notifications_qs = []
    profile = getattr(user, "profile", None)
    if profile and hasattr(profile, "notifications"):
        try:
            notifications_qs = profile.notifications.all().order_by("-created_at")
        except Exception:
            notifications_qs = []

    if not notifications_qs and hasattr(user, "notifications"):
        try:
            notifications_qs = user.notifications.all().order_by("-created_at")
        except Exception:
            notifications_qs = []

    try:
        paginator = Paginator(notifications_qs, 20)
        page = request.GET.get("page")
        notifications_page = paginator.get_page(page)
    except Exception:
        notifications_page = []

    return render(request, "notifications/notifications.html", {"notifications": notifications_page})


# --------- Engineer Views ---------
@engineer_only
def engineer_dashboard(request):
    """
    Engineer dashboard with optional category filtering and additional KPIs.
    """
    category_param = request.GET.get("category")
    categories = MaterialCategory.objects.filter(is_active=True)

    orders_qs = request.user.profile.orders.select_related("material", "supplier").order_by("-created_at")

    selected_category: Optional[MaterialCategory] = None
    if category_param:
        try:
            if str(category_param).isdigit():
                sel_cat = MaterialCategory.objects.get(pk=int(category_param))
            else:
                sel_cat = MaterialCategory.objects.filter(
                    Q(slug__iexact=category_param) | Q(name__iexact=category_param)
                ).first()
                if sel_cat is None:
                    raise MaterialCategory.DoesNotExist()
            selected_category = sel_cat

            try:
                Material._meta.get_field("primary_category")
                has_primary = True
            except FieldDoesNotExist:
                has_primary = False

            try:
                Material._meta.get_field("categories")
                has_categories = True
            except FieldDoesNotExist:
                has_categories = False

            if has_primary or has_categories:
                q = Q()
                if has_primary:
                    q |= Q(material__primary_category=sel_cat)
                if has_categories:
                    q |= Q(material__categories=sel_cat)
                orders_qs = orders_qs.filter(q).distinct()
            else:
                orders_qs = orders_qs.filter(material__category__iexact=sel_cat.name)
        except (MaterialCategory.DoesNotExist, ValueError):
            selected_category = None

    total_orders = orders_qs.count()
    total_spent = orders_qs.aggregate(total=Sum("total_price"))["total"] or 0

    status_counts = orders_qs.values("status").annotate(count=Count("id"))
    status_map = {entry["status"]: entry["count"] for entry in status_counts}

    STATUS_DEFINITION = [
        ("pending", "Pending", "yellow"),
        ("confirmed", "Confirmed", "orange"),
        ("dispatched", "Dispatched", "blue"),
        ("delivered", "Delivered", "green"),
        ("cancelled", "Cancelled", "gray"),
    ]
    status_items = []
    for key, label, color in STATUS_DEFINITION:
        status_items.append({"key": key, "label": label, "color": color, "count": status_map.get(key, 0)})

    top_suppliers = (
        orders_qs.values("supplier__id", "supplier__company_name")
        .annotate(orders_count=Count("id"), sales=Sum("total_price"))
        .order_by("-orders_count")[:6]
    )

    top_materials = (
        orders_qs.values("material__id", "material__name")
        .annotate(orders_count=Count("id"))
        .order_by("-orders_count")[:6]
    )

    recent_orders = orders_qs.select_related("material", "supplier")[:8]

    try:
        default_threshold = int(getattr(settings, "LOW_STOCK_THRESHOLD", 5))
    except Exception:
        default_threshold = 5
    try:
        low_stock_threshold = int(request.GET.get("low_stock_threshold", default_threshold))
    except (TypeError, ValueError):
        low_stock_threshold = default_threshold

    low_stock_qs = Material.objects.filter(stock_level__lte=low_stock_threshold, is_active=True).order_by("stock_level")
    low_stock_count = low_stock_qs.count()
    low_stock_materials = list(low_stock_qs[:10])

    paginator = Paginator(orders_qs, 10)
    page_number = request.GET.get("page")
    orders_page = paginator.get_page(page_number)

    context = {
        "orders": orders_page,
        "categories": categories,
        "selected_category": selected_category,
        "total_orders": total_orders,
        "total_spent": total_spent,
        "status_map": status_map,
        "status_items": status_items,
        "top_suppliers": top_suppliers,
        "top_materials": top_materials,
        "recent_orders": recent_orders,
        "low_stock_count": low_stock_count,
        "low_stock_materials": low_stock_materials,
        "low_stock_threshold": low_stock_threshold,
    }
    return render(request, "engineers/engineer_dashboard.html", context)


def material_list(request):
    """
    List materials with search and category filtering.
    """
    query = request.GET.get("q", "").strip()
    category_param = request.GET.get("category", "").strip()
    materials_qs = Material.objects.filter(is_active=True, stock_level__gt=0)
    categories = MaterialCategory.objects.filter(is_active=True)

    if query:
        materials_qs = materials_qs.filter(
            Q(name__icontains=query) | Q(description__icontains=query) | Q(supplier__company_name__icontains=query)
        )

    selected_category = None
    if category_param:
        try:
            if category_param.isdigit():
                sel_cat = MaterialCategory.objects.get(pk=int(category_param))
            else:
                sel_cat = MaterialCategory.objects.filter(Q(slug__iexact=category_param) | Q(name__iexact=category_param)).first()
                if sel_cat is None:
                    raise MaterialCategory.DoesNotExist()
            selected_category = sel_cat

            try:
                Material._meta.get_field("primary_category")
                has_primary = True
            except FieldDoesNotExist:
                has_primary = False

            try:
                Material._meta.get_field("categories")
                has_categories = True
            except FieldDoesNotExist:
                has_categories = False

            if has_primary or has_categories:
                q = Q()
                if has_primary:
                    q |= Q(primary_category=sel_cat)
                if has_categories:
                    q |= Q(categories=sel_cat)
                materials_qs = materials_qs.filter(q).distinct()
            else:
                materials_qs = materials_qs.filter(category__iexact=sel_cat.name)
        except (MaterialCategory.DoesNotExist, ValueError):
            selected_category = None

    prefetch_fields = []
    try:
        Material._meta.get_field("categories")
        prefetch_fields.append("categories")
    except FieldDoesNotExist:
        pass

    if prefetch_fields:
        materials_qs = materials_qs.prefetch_related(*prefetch_fields).select_related("supplier")
    else:
        materials_qs = materials_qs.select_related("supplier")

    paginator = Paginator(materials_qs, 12)
    page_number = request.GET.get("page")
    materials = paginator.get_page(page_number)

    context = {"materials": materials, "categories": categories, "query": query, "selected_category": selected_category}
    return render(request, "engineers/material_list.html", context)


@engineer_only
def material_detail(request, pk):
    material = get_object_or_404(Material, pk=pk, is_active=True)
    supplier = material.supplier
    reviews = supplier.reviews.all().order_by("-created_at")[:5]
    return render(request, "engineers/material_detail.html", {"material": material, "supplier": supplier, "reviews": reviews})


@engineer_only
def place_order(request, material_id):
    """
    Engineers place an order for a material with validation, concurrency safety,
    and automatic delivery-agent assignment.
    """
    material = get_object_or_404(Material, pk=material_id, is_active=True)
    supplier = material.supplier

    if request.method == "POST":
        form = OrderForm(request.POST, material=material)
        if form.is_valid():
            requested_qty = form.cleaned_data.get("quantity")
            try:
                with transaction.atomic():
                    m = Material.objects.select_for_update().get(pk=material.pk)

                    if requested_qty <= 0:
                        messages.error(request, "Quantity must be greater than zero.")
                    elif requested_qty > m.stock_level:
                        messages.error(request, f"Requested quantity ({requested_qty}) exceeds available stock ({m.stock_level}).")
                    else:
                        order = form.save(commit=False)
                        order.engineer = request.user.profile
                        order.supplier = supplier
                        order.material = m
                        order.total_price = m.unit_price * order.quantity
                        order.save()

                        m.stock_level -= order.quantity
                        m.save()

                        assigned_delivery = assign_delivery_agent(order)
                        if assigned_delivery:
                            messages.success(request, f"Order placed and delivery assigned to agent {getattr(assigned_delivery.delivery_agent.user, 'username', '')}.")
                        else:
                            messages.info(request, "Order placed. No delivery agent available right now; it will be assigned later.")

                        # send emails notifying engineer and supplier (best-effort)
                        try:
                            send_order_placed(order)
                        except Exception:
                            logger.exception("Failed to send order placed emails for order %s", getattr(order, "id", None))

                        return redirect("engineer_dashboard")
            except Material.DoesNotExist:
                messages.error(request, "Material no longer exists.")
            except Exception as exc:
                logger.exception("Error placing order")
                messages.error(request, f"An error occurred while placing the order: {exc}")
        else:
            messages.error(request, "Please fix the errors in the form below.")
    else:
        form = OrderForm(material=material, initial={"material": material})

    return render(request, "engineers/place_order.html", {"material": material, "form": form, "supplier": supplier})


@engineer_only
def order_list(request):
    orders = request.user.profile.orders.select_related("material", "supplier").order_by("-created_at")
    return render(request, "engineers/order_list.html", {"orders": orders})


@engineer_only
@require_POST
def cancel_order(request, order_id):
    order = get_object_or_404(Order, pk=order_id, engineer=request.user.profile)

    cancellable = ("pending", "confirmed")
    if order.status not in cancellable:
        messages.error(request, "This order cannot be cancelled at its current status.")
        return redirect("order_detail", order_id=order.id)

    try:
        with transaction.atomic():
            material = Material.objects.select_for_update().get(pk=order.material.pk)
            material.stock_level = material.stock_level + order.quantity
            material.save(update_fields=["stock_level"])

            order.status = "cancelled"
            order.save(update_fields=["status"])

        messages.success(request, "Order cancelled and stock restored.")
    except Exception as exc:
        logger.exception("Error cancelling order %s", order.id)
        messages.error(request, "Could not cancel the order. Please try again later.")

    return redirect("order_detail", order_id=order.id)


@engineer_only
def order_detail(request, order_id):
    order = get_object_or_404(Order, pk=order_id, engineer=request.user.profile)
    pending_statuses = ["pending", "confirmed"]
    return render(request, "engineers/order_detail.html", {"order": order, "pending_statuses": pending_statuses})


@engineer_only
def review_supplier(request, supplier_id):
    supplier = SupplierProfile.objects.filter(pk=supplier_id).first()
    if supplier is None:
        supplier = SupplierProfile.objects.filter(profile__pk=supplier_id).first()
    if supplier is None:
        supplier = SupplierProfile.objects.filter(profile__user__pk=supplier_id).first()
    if supplier is None:
        messages.error(request, "Supplier not found. Please try again or contact support.")
        return redirect("material_list")

    if request.method == "POST":
        form = SupplierReviewForm(request.POST)
        if form.is_valid():
            review = form.save(commit=False)
            review.engineer = request.user.profile
            review.supplier = supplier
            review.save()
            messages.success(request, "Review submitted.")
            return redirect("material_list")
    else:
        form = SupplierReviewForm()
    return render(request, "engineers/review_supplier.html", {"form": form, "supplier": supplier})


# --------- Supplier Views ---------
@supplier_only
def supplier_dashboard(request):
    supplier = SupplierProfile.objects.filter(profile__user=request.user).first()
    if not supplier:
        return redirect("supplier_profile")

    categories = MaterialCategory.objects.filter(is_active=True)
    materials_qs = Material.objects.filter(supplier=supplier)

    materials_count = materials_qs.count()
    orders_qs = Order.objects.filter(supplier=supplier).select_related("material", "engineer").order_by("-created_at")
    recent_orders = orders_qs[:8]
    orders_count = orders_qs.count()
    total_sales = orders_qs.aggregate(total=Sum("total_price"))["total"] or 0

    avg_rating = SupplierReview.objects.filter(supplier=supplier).aggregate(avg=Avg("rating"))["avg"] or 0.0

    low_stock_threshold = 5
    low_stock_materials = materials_qs.filter(stock_level__lte=low_stock_threshold).order_by("stock_level")[:6]
    low_stock_count = low_stock_materials.count()

    status_counts = orders_qs.values("status").annotate(count=Count("id"))
    status_map = {e["status"]: e["count"] for e in status_counts}

    STATUS_DEFINITION = [
        ("pending", "Pending", "yellow"),
        ("confirmed", "Confirmed", "orange"),
        ("dispatched", "Dispatched", "blue"),
        ("delivered", "Delivered", "green"),
        ("cancelled", "Cancelled", "gray"),
    ]
    status_items = []
    for key, label, color in STATUS_DEFINITION:
        status_items.append({"key": key, "label": label, "color": color, "count": status_map.get(key, 0)})

    top_engineers = (
        orders_qs.values("engineer__id", "engineer__user__username")
        .annotate(orders_count=Count("id"), spend=Sum("total_price"))
        .order_by("-orders_count")[:6]
    )

    top_materials = (
        orders_qs.values("material__id", "material__name")
        .annotate(orders_count=Count("id"))
        .order_by("-orders_count")[:6]
    )

    recent_reviews = SupplierReview.objects.filter(supplier=supplier).select_related("engineer__user").order_by("-created_at")[:5]

    page = request.GET.get("page")
    paginator = Paginator(materials_qs.order_by("-id"), 12)
    materials_page = paginator.get_page(page)

    context = {
        "supplier": supplier,
        "categories": categories,
        "materials": materials_page,
        "materials_count": materials_count,
        "recent_orders": recent_orders,
        "orders_count": orders_count,
        "total_sales": total_sales,
        "avg_rating": avg_rating,
        "low_stock_materials": low_stock_materials,
        "low_stock_count": low_stock_count,
        "status_items": status_items,
        "top_engineers": top_engineers,
        "top_materials": top_materials,
        "recent_reviews": recent_reviews,
    }
    return render(request, "supplier/supplier_dashboard.html", context)


@supplier_only
def supplier_orders(request):
    supplier_profile = SupplierProfile.objects.filter(profile=request.user.profile).first()
    if not supplier_profile:
        messages.error(request, "No supplier profile found. Please contact support.")
        return redirect("login")
    orders = Order.objects.filter(supplier=supplier_profile).order_by("-created_at")
    return render(request, "supplier/supplier_orders.html", {"orders": orders})


@supplier_only
def supplier_materials(request):
    supplier_profile = SupplierProfile.objects.filter(profile=request.user.profile).first()
    if not supplier_profile:
        messages.error(request, "No supplier profile found. Please contact support.")
        return redirect("login")
    materials = Material.objects.filter(supplier=supplier_profile)
    return render(request, "supplier/supplier_materials.html", {"materials": materials})


@supplier_only
def supplier_add_material(request):
    supplier_profile = SupplierProfile.objects.filter(profile=request.user.profile).first()
    if not supplier_profile:
        messages.error(request, "No supplier profile found. Please contact support.")
        return redirect("login")
    if request.method == "POST":
        form = MaterialForm(request.POST, request.FILES, supplier=supplier_profile)
        if form.is_valid():
            material = form.save(commit=False)
            if not getattr(material, "supplier", None):
                material.supplier = supplier_profile
            material.save()
            if hasattr(form, "cleaned_data") and "categories" in form.cleaned_data:
                material.categories.set(form.cleaned_data.get("categories") or [])
            messages.success(request, f"Material '{material.name}' added successfully.")
            return redirect("supplier_materials")
        else:
            messages.error(request, "Please fix the errors on the form below.")
    else:
        form = MaterialForm(supplier=supplier_profile)
    return render(request, "supplier/supplier_add_material.html", {"form": form})


@supplier_only
def supplier_material_detail(request, pk):
    supplier_profile = SupplierProfile.objects.filter(profile=request.user.profile).first()
    if not supplier_profile:
        messages.error(request, "No supplier profile found. Please contact support.")
        return redirect("login")
    material = get_object_or_404(Material, pk=pk, supplier=supplier_profile)
    orders = Order.objects.filter(material=material)
    return render(request, "supplier/supplier_material_detail.html", {"material": material, "orders": orders})


@login_required
def supplier_edit_material(request, pk):
    material = get_object_or_404(Material, pk=pk)

    supplier_owner = getattr(material.supplier, "profile", None)
    if not supplier_owner or supplier_owner.user != request.user:
        return HttpResponseForbidden("You are not allowed to edit this material.")

    if request.method == "POST":
        form = MaterialForm(request.POST, request.FILES, instance=material, supplier=material.supplier)
        if form.is_valid():
            form.save()
            messages.success(request, "Material updated successfully.")
            return redirect("supplier_material_detail", material.id)
        else:
            messages.error(request, "Please correct the errors below.")
    else:
        form = MaterialForm(instance=material, supplier=material.supplier)

    return render(request, "supplier/supplier_edit_material.html", {"form": form, "supplier": material.supplier, "material": material})


@require_POST
@login_required
def supplier_delete_material(request, pk):
    material = get_object_or_404(Material, pk=pk)
    supplier_owner = getattr(material.supplier, "profile", None)
    if not supplier_owner or supplier_owner.user != request.user:
        return HttpResponseForbidden("You are not allowed to delete this material.")

    material.delete()
    messages.success(request, "Material has been deleted.")
    return redirect("supplier_materials")


@supplier_only
def supplier_profile(request):
    supplier_profile = SupplierProfile.objects.filter(profile=request.user.profile).first()
    if not supplier_profile:
        messages.error(request, "No supplier profile found. Please contact support.")
        return redirect("login")
    return render(request, "supplier/supplier_profile.html", {"supplier": supplier_profile})


@supplier_only
def supplier_reviews(request):
    supplier_profile = SupplierProfile.objects.filter(profile=request.user.profile).first()
    if not supplier_profile:
        messages.error(request, "No supplier profile found. Please contact support.")
        return redirect("login")
    reviews = SupplierReview.objects.filter(supplier=supplier_profile)
    return render(request, "supplier/supplier_reviews.html", {"reviews": reviews, "supplier": supplier_profile})


# --------- Delivery Agent Views ---------
@delivery_only
def delivery_agent_dashboard(request):
    agent_profile = getattr(request.user, "profile", None)
    if not agent_profile:
        messages.error(request, "No delivery profile found.")
        return redirect("login")

    deliveries_qs = Delivery.objects.filter(delivery_agent=agent_profile).select_related("order__material", "order__engineer").order_by("-id")

    total_assigned = deliveries_qs.count()
    delivered = deliveries_qs.filter(delivered_at__isnull=False).count()
    dispatched = deliveries_qs.filter(dispatched_at__isnull=False).count()
    in_transit = deliveries_qs.filter(dispatched_at__isnull=False, delivered_at__isnull=True).count()
    pending = deliveries_qs.filter(dispatched_at__isnull=True).count()

    recent_deliveries = deliveries_qs[:8]

    paginator = Paginator(deliveries_qs, 12)
    page = request.GET.get("page")
    deliveries_page = paginator.get_page(page)

    context = {
        "agent_profile": agent_profile,
        "total_assigned": total_assigned,
        "in_transit": in_transit,
        "dispatched": dispatched,
        "delivered": delivered,
        "pending": pending,
        "recent_deliveries": recent_deliveries,
        "deliveries": deliveries_page,
    }
    return render(request, "delivery/delivery_dashboard.html", context)


@delivery_only
def deliveries_list(request):
    agent_profile = getattr(request.user, "profile", None)
    if not agent_profile:
        messages.error(request, "No delivery profile found.")
        return redirect("login")

    q = request.GET.get("q", "").strip()
    status = request.GET.get("status", "").strip().lower()

    qs = Delivery.objects.filter(delivery_agent=agent_profile).select_related("order__material", "order__engineer").order_by("-id")

    if status:
        if status == "pending":
            qs = qs.filter(dispatched_at__isnull=True)
        elif status in ("dispatched", "in_transit"):
            qs = qs.filter(dispatched_at__isnull=False, delivered_at__isnull=True)
        elif status == "delivered":
            qs = qs.filter(delivered_at__isnull=False)
        else:
            qs = qs.none()
            messages.warning(request, "That status is not supported by the delivery model.")

    if q:
        if q.isdigit():
            qs = qs.filter(order__id=int(q))
        else:
            qs = qs.filter(Q(order__material__name__icontains=q) | Q(order__engineer__user__username__icontains=q))

    paginator = Paginator(qs, 20)
    page = request.GET.get("page")
    deliveries = paginator.get_page(page)

    return render(request, "delivery/deliveries_list.html", {"deliveries": deliveries, "q": q, "status": status})


@delivery_only
def delivery_detail(request, pk):
    agent_profile = getattr(request.user, "profile", None)
    delivery = get_object_or_404(Delivery, pk=pk)

    if delivery.delivery_agent and delivery.delivery_agent != agent_profile:
        return HttpResponseForbidden("You are not assigned to this delivery.")

    order = getattr(delivery, "order", None)

    if getattr(delivery, "delivered_at", None):
        next_allowed = []
    elif getattr(delivery, "dispatched_at", None):
        next_allowed = ["delivered"]
    else:
        next_allowed = ["dispatched"]

    return render(request, "delivery/delivery_detail.html", {"delivery": delivery, "order": order, "next_allowed": next_allowed, "agent_profile": agent_profile})


@delivery_only
@require_POST
def delivery_update_status(request, pk):
    agent_profile = getattr(request.user, "profile", None)
    delivery = get_object_or_404(Delivery, pk=pk)

    if delivery.delivery_agent and delivery.delivery_agent != agent_profile:
        return HttpResponseForbidden("You are not assigned to this delivery.")

    action = request.POST.get("action", "").strip().lower()
    notes = request.POST.get("notes", "").strip()
    current_location = request.POST.get("current_location", "").strip()

    allowed = {"dispatched", "delivered"}
    if action not in allowed:
        messages.error(request, "Invalid or unsupported status action for this delivery.")
        return redirect("delivery_detail", pk=delivery.pk)

    try:
        with transaction.atomic():
            if notes:
                existing = delivery.notes or ""
                timestamp = timezone.now().strftime("%Y-%m-%d %H:%M")
                delivery.notes = f"{existing}\n[{timestamp}] {notes}" if existing else f"[{timestamp}] {notes}"

            if current_location and hasattr(delivery, "current_location"):
                delivery.current_location = current_location

            dispatch_or_deliver = None
            if action == "dispatched":
                if hasattr(delivery, "dispatched_at") and not getattr(delivery, "dispatched_at", None):
                    delivery.dispatched_at = timezone.now()
                    dispatch_or_deliver = "dispatched"
            elif action == "delivered":
                if hasattr(delivery, "delivered_at") and not getattr(delivery, "delivered_at", None):
                    delivery.delivered_at = timezone.now()
                    dispatch_or_deliver = "delivered"
                if hasattr(delivery, "dispatched_at") and not getattr(delivery, "dispatched_at", None):
                    delivery.dispatched_at = timezone.now()

                if hasattr(delivery, "order") and delivery.order and hasattr(delivery.order, "status"):
                    delivery.order.status = "delivered"
                    delivery.order.save(update_fields=["status"])

            if hasattr(delivery, "last_updated_by"):
                delivery.last_updated_by = agent_profile

            delivery.save()

        # send emails after successful save (best-effort)
        try:
            if dispatch_or_deliver == "dispatched":
                send_order_dispatched(delivery)
            elif dispatch_or_deliver == "delivered":
                send_order_delivered(delivery)
        except Exception:
            logger.exception("Failed to send delivery status email for delivery %s", delivery.pk)

        messages.success(request, f"Delivery updated to '{action}'.")
    except Exception as exc:
        logger.exception("Error updating delivery %s", delivery.pk)
        messages.error(request, "Could not update delivery status. Try again.")

    return redirect("delivery_detail", pk=delivery.pk)