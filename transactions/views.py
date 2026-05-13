# Standard library imports
import json
import logging
from decimal import Decimal, InvalidOperation

# Django core imports
from django.http import JsonResponse, HttpResponse
from django.urls import reverse
from django.shortcuts import redirect, render

# Class-based views
from django.views.generic import DetailView, ListView
from django.views.generic.edit import CreateView, UpdateView, DeleteView

# Authentication and permissions
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin

# Third-party packages
from openpyxl import Workbook

# Local app imports
from accounts.models import Customer
from .models import Sale, Purchase
from .forms import PurchaseForm
from .audit import AuditLogger
from .exceptions import InsufficientStockError, TransactionError
from .repositories import (
    InventoryRepository,
    PurchaseRepository,
    SaleRepository,
)
from .services import CreatePurchaseService, CreateSaleService


logger = logging.getLogger(__name__)


def is_ajax(request):
    return request.META.get('HTTP_X_REQUESTED_WITH') == 'XMLHttpRequest'


def export_sales_to_excel(request):
    # Create a workbook and select the active worksheet.
    workbook = Workbook()
    worksheet = workbook.active
    worksheet.title = 'Sales'

    # Define the column headers
    columns = [
        'ID', 'Date', 'Customer', 'Sub Total',
        'Grand Total', 'Tax Amount', 'Tax Percentage',
        'Amount Paid', 'Amount Change'
    ]
    worksheet.append(columns)

    # Fetch sales data
    sales = Sale.objects.all()

    for sale in sales:
        # Convert timezone-aware datetime to naive datetime
        if sale.date_added.tzinfo is not None:
            date_added = sale.date_added.replace(tzinfo=None)
        else:
            date_added = sale.date_added

        worksheet.append([
            sale.id,
            date_added,
            sale.customer.phone,
            sale.sub_total,
            sale.grand_total,
            sale.tax_amount,
            sale.tax_percentage,
            sale.amount_paid,
            sale.amount_change
        ])

    # Set up the response to send the file
    response = HttpResponse(
        content_type=(
            'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        )
    )
    response['Content-Disposition'] = 'attachment; filename=sales.xlsx'
    workbook.save(response)

    return response


def export_purchases_to_excel(request):
    # Create a workbook and select the active worksheet.
    workbook = Workbook()
    worksheet = workbook.active
    worksheet.title = 'Purchases'

    # Define the column headers
    columns = [
        'ID', 'Item', 'Description', 'Vendor', 'Order Date',
        'Delivery Date', 'Quantity', 'Delivery Status',
        'Price per item (Ksh)', 'Total Value'
    ]
    worksheet.append(columns)

    # Fetch purchases data
    purchases = Purchase.objects.all()

    for purchase in purchases:
        # Convert timezone-aware datetime to naive datetime
        delivery_tzinfo = purchase.delivery_date.tzinfo
        order_tzinfo = purchase.order_date.tzinfo

        if delivery_tzinfo or order_tzinfo is not None:
            delivery_date = purchase.delivery_date.replace(tzinfo=None)
            order_date = purchase.order_date.replace(tzinfo=None)
        else:
            delivery_date = purchase.delivery_date
            order_date = purchase.order_date
        worksheet.append([
            purchase.id,
            purchase.item.name,
            purchase.description,
            purchase.vendor.name,
            order_date,
            delivery_date,
            purchase.quantity,
            purchase.get_delivery_status_display(),
            purchase.price,
            purchase.total_value
        ])

    # Set up the response to send the file
    response = HttpResponse(
        content_type=(
            'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        )
    )
    response['Content-Disposition'] = 'attachment; filename=purchases.xlsx'
    workbook.save(response)

    return response


class SaleListView(LoginRequiredMixin, ListView):
    """
    View to list all sales with pagination.
    """

    model = Sale
    template_name = "transactions/sales_list.html"
    context_object_name = "sales"
    paginate_by = 10
    ordering = ['date_added']


class SaleDetailView(LoginRequiredMixin, DetailView):
    """
    View to display details of a specific sale.
    """

    model = Sale
    template_name = "transactions/saledetail.html"


@login_required
def SaleCreateView(request):
    context = {
        "active_icon": "sales",
        "customers": [c.to_select2() for c in Customer.objects.all()],
    }

    if request.method != 'POST' or not is_ajax(request=request):
        return render(request, "transactions/sale_create.html", context=context)

    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({
            'status': 'error',
            'message': 'Invalid JSON format in request body',
        }, status=400)

    try:
        customer_id = int(data['customer'])
        tax_percentage = Decimal(str(data.get('tax_percentage', 0)))
        amount_paid = Decimal(str(data['amount_paid']))
        items = [
            {'item_id': int(it['id']), 'qty': int(it['quantity'])}
            for it in data['items']
        ]
    except (KeyError, ValueError, TypeError, InvalidOperation) as e:
        return JsonResponse({
            'status': 'error',
            'message': f'Invalid request data: {e}',
        }, status=400)

    service = CreateSaleService(
        InventoryRepository(),
        SaleRepository(),
        AuditLogger(),
    )

    try:
        sale = service.execute(
            customer_id=customer_id,
            items=items,
            tax_percentage=tax_percentage,
            amount_paid=amount_paid,
            user_id=request.user.id,
        )
    except InsufficientStockError as e:
        return JsonResponse({
            'status': 'error',
            'message': str(e),
            'item_id': e.item_id,
            'requested': e.requested,
            'available': e.available,
        }, status=400)
    except TransactionError as e:
        return JsonResponse({
            'status': 'error',
            'message': str(e),
        }, status=400)
    except Exception:
        logger.exception('Unexpected error in SaleCreateView')
        return JsonResponse({
            'status': 'error',
            'message': 'Unexpected error',
        }, status=500)

    return JsonResponse({
        'status': 'success',
        'message': 'Sale created successfully!',
        'sale_id': sale.id,
        'redirect': '/transactions/sales/',
    })


class SaleDeleteView(LoginRequiredMixin, UserPassesTestMixin, DeleteView):
    """
    View to delete a sale.
    """

    model = Sale
    template_name = "transactions/saledelete.html"

    def get_success_url(self):
        """
        Redirect to the sales list after successful deletion.
        """
        return reverse("saleslist")

    def test_func(self):
        """
        Allow deletion only for superusers.
        """
        return self.request.user.is_superuser


class PurchaseListView(LoginRequiredMixin, ListView):
    """
    View to list all purchases with pagination.
    """

    model = Purchase
    template_name = "transactions/purchases_list.html"
    context_object_name = "purchases"
    paginate_by = 10


class PurchaseDetailView(LoginRequiredMixin, DetailView):
    """
    View to display details of a specific purchase.
    """

    model = Purchase
    template_name = "transactions/purchasedetail.html"


class PurchaseCreateView(LoginRequiredMixin, CreateView):
    """
    Crea una nueva compra delegando a CreatePurchaseService.
    El servicio garantiza atomicidad y el incremento de stock con lock.
    """

    model = Purchase
    form_class = PurchaseForm
    template_name = "transactions/purchases_form.html"

    def get_success_url(self):
        return reverse("purchaseslist")

    def form_valid(self, form):
        service = CreatePurchaseService(
            InventoryRepository(),
            PurchaseRepository(),
            AuditLogger(),
        )
        cd = form.cleaned_data
        try:
            service.execute(
                item_id=cd['item'].id,
                vendor_id=cd['vendor'].id,
                quantity=cd['quantity'],
                price=cd['price'],
                description=cd.get('description') or '',
                delivery_date=cd.get('delivery_date'),
                delivery_status=cd.get('delivery_status', 'P'),
                user_id=self.request.user.id,
            )
        except TransactionError as e:
            form.add_error(None, str(e))
            return self.form_invalid(form)
        except Exception:
            logger.exception('Unexpected error in PurchaseCreateView')
            form.add_error(None, 'Unexpected error')
            return self.form_invalid(form)

        return redirect(self.get_success_url())


class PurchaseUpdateView(LoginRequiredMixin, UpdateView):
    """
    View to update an existing purchase.
    """

    model = Purchase
    form_class = PurchaseForm
    template_name = "transactions/purchases_form.html"

    def get_success_url(self):
        """
        Redirect to the purchases list after successful form submission.
        """
        return reverse("purchaseslist")


class PurchaseDeleteView(LoginRequiredMixin, UserPassesTestMixin, DeleteView):
    """
    View to delete a purchase.
    """

    model = Purchase
    template_name = "transactions/purchasedelete.html"

    def get_success_url(self):
        """
        Redirect to the purchases list after successful deletion.
        """
        return reverse("purchaseslist")

    def test_func(self):
        """
        Allow deletion only for superusers.
        """
        return self.request.user.is_superuser
