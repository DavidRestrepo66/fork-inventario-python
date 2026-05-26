from decimal import Decimal
from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from django.utils import timezone
from datetime import timedelta

from accounts.models import Profile, Vendor, Customer
from store.models import Category, Item, Delivery
from transactions.models import Sale, SaleDetail, Purchase
from transactions.repositories import InventoryRepository, PurchaseRepository, SaleRepository
from transactions.audit import AuditLogger
from transactions.services import CreateSaleService, CreatePurchaseService
from bills.models import Bill
from invoice.models import Invoice


class Command(BaseCommand):
    help = 'Pobla la base de datos con datos de prueba para MediStore'

    def add_arguments(self, parser):
        parser.add_argument(
            '--flush',
            action='store_true',
            help='Elimina datos existentes antes de sembrar',
        )

    def handle(self, *args, **options):
        if options['flush']:
            self._flush()

        self._create_users()
        self._create_vendors()
        self._create_customers()
        self._create_catalog()
        self._create_purchases()
        self._create_sales()
        self._create_invoices()
        self._create_bills()
        self._create_deliveries()

        self.stdout.write(self.style.SUCCESS('Base de datos poblada exitosamente.'))
        self.stdout.write('')
        self.stdout.write('Usuarios creados:')
        self.stdout.write('  admin / admin123  (superusuario)')
        self.stdout.write('  cajero / cajero123')
        self.stdout.write('  bodeguero / bodega123')

    # ------------------------------------------------------------------
    def _flush(self):
        self.stdout.write('Limpiando datos existentes...')
        Invoice.objects.all().delete()
        Bill.objects.all().delete()
        Delivery.objects.all().delete()
        SaleDetail.objects.all().delete()
        Sale.objects.all().delete()
        Purchase.objects.all().delete()
        Item.objects.all().delete()
        Category.objects.all().delete()
        Customer.objects.all().delete()
        Vendor.objects.all().delete()
        Profile.objects.all().delete()
        User.objects.filter(is_superuser=False).delete()

    # ------------------------------------------------------------------
    def _create_users(self):
        self.stdout.write('Creando usuarios...')

        if not User.objects.filter(username='admin').exists():
            admin = User.objects.create_superuser('admin', 'admin@medistore.com', 'admin123')
            Profile.objects.get_or_create(
                user=admin,
                defaults=dict(
                    first_name='Carlos', last_name='Administrador',
                    email='admin@medistore.com', role='AD', status='A',
                )
            )

        for username, password, first, last, role in [
            ('cajero',    'cajero123', 'Laura',   'Gómez',   'OP'),
            ('bodeguero', 'bodega123', 'Andrés',  'Torres',  'OP'),
        ]:
            if not User.objects.filter(username=username).exists():
                u = User.objects.create_user(username, f'{username}@medistore.com', password)
                Profile.objects.get_or_create(
                    user=u,
                    defaults=dict(
                        first_name=first, last_name=last,
                        email=f'{username}@medistore.com', role=role, status='A',
                    )
                )

    # ------------------------------------------------------------------
    def _create_vendors(self):
        self.stdout.write('Creando proveedores...')
        vendors = [
            ('PharmaCorp',    3001234567, 'Calle 80 #45-10, Bogotá'),
            ('MediSuministros', 3109876543, 'Av. El Dorado #68-50, Bogotá'),
            ('BioLabs SA',    6014567890, 'Carrera 7 #32-00, Bogotá'),
        ]
        for name, phone, address in vendors:
            Vendor.objects.get_or_create(name=name, defaults=dict(phone_number=phone, address=address))

    # ------------------------------------------------------------------
    def _create_customers(self):
        self.stdout.write('Creando clientes...')
        customers = [
            ('Juan',    'Pérez',   'Calle 45 #12-30', 'juan@mail.com',    '3119876543'),
            ('María',   'López',   'Carrera 9 #18-05', 'maria@mail.com',  '3204561230'),
            ('Carlos',  'Ramírez', 'Av. 68 #30-15',   'carlos@mail.com', '3157890123'),
            ('Ana',     'Martínez','Calle 100 #15-60', 'ana@mail.com',    '3001237890'),
            ('Luis',    'Hernández','Kr 50 #22-10',   'luis@mail.com',   '3124560987'),
        ]
        for first, last, addr, email, phone in customers:
            Customer.objects.get_or_create(
                phone=phone,
                defaults=dict(first_name=first, last_name=last, address=addr, email=email)
            )

    # ------------------------------------------------------------------
    def _create_catalog(self):
        self.stdout.write('Creando categorías e items...')
        vendor = Vendor.objects.get(name='PharmaCorp')

        analgesicos, _ = Category.objects.get_or_create(name='Analgésicos')
        antibioticos, _ = Category.objects.get_or_create(name='Antibióticos')
        vitaminas, _    = Category.objects.get_or_create(name='Vitaminas')
        topicos, _      = Category.objects.get_or_create(name='Tópicos')

        items = [
            ('Ibuprofeno 400mg',     analgesicos,  120, 2500,  vendor),
            ('Acetaminofén 500mg',   analgesicos,   80, 1800,  vendor),
            ('Naproxeno 250mg',      analgesicos,   60, 3200,  vendor),
            ('Amoxicilina 500mg',    antibioticos,  40, 8500,  Vendor.objects.get(name='MediSuministros')),
            ('Azitromicina 500mg',   antibioticos,  30, 12000, Vendor.objects.get(name='MediSuministros')),
            ('Vitamina C 1000mg',    vitaminas,     90, 4500,  Vendor.objects.get(name='BioLabs SA')),
            ('Vitamina D3 2000UI',   vitaminas,     50, 6000,  Vendor.objects.get(name='BioLabs SA')),
            ('Crema Antifúngica',    topicos,       35, 9800,  vendor),
            ('Gel Antibacterial',    topicos,      100, 3500,  vendor),
        ]
        self.items = {}
        for name, cat, qty, price, vend in items:
            item, _ = Item.objects.get_or_create(
                name=name,
                defaults=dict(
                    description=f'{name} — uso farmacéutico',
                    category=cat, quantity=qty, price=price, vendor=vend,
                )
            )
            self.items[name] = item

    # ------------------------------------------------------------------
    def _create_purchases(self):
        self.stdout.write('Creando compras (reabastecimientos)...')
        admin = User.objects.get(username='admin')
        inv_repo  = InventoryRepository()
        purch_repo = PurchaseRepository()
        audit     = AuditLogger()
        service   = CreatePurchaseService(inv_repo, purch_repo, audit)

        purchases = [
            ('Ibuprofeno 400mg',   'PharmaCorp',       200, Decimal('1500'), 'Reabastecimiento mensual'),
            ('Acetaminofén 500mg', 'PharmaCorp',       150, Decimal('1100'), 'Pedido urgente'),
            ('Amoxicilina 500mg',  'MediSuministros',   80, Decimal('5000'), 'Stock bajo'),
            ('Vitamina C 1000mg',  'BioLabs SA',       120, Decimal('2800'), 'Temporada de gripa'),
        ]

        for item_name, vendor_name, qty, price, desc in purchases:
            item   = self.items[item_name]
            vendor = Vendor.objects.get(name=vendor_name)
            delivery = timezone.now() + timedelta(days=3)
            try:
                service.execute(
                    item_id=item.id,
                    vendor_id=vendor.id,
                    quantity=qty,
                    price=price,
                    description=desc,
                    delivery_date=delivery,
                    delivery_status='S',
                    user_id=admin.id,
                )
            except Exception as e:
                self.stdout.write(self.style.WARNING(f'  Purchase skip: {e}'))

    # ------------------------------------------------------------------
    def _create_sales(self):
        self.stdout.write('Creando ventas...')
        admin   = User.objects.get(username='admin')
        service = CreateSaleService(InventoryRepository(), SaleRepository(), AuditLogger())

        customers = list(Customer.objects.all())
        sales_data = [
            (customers[0], [('Ibuprofeno 400mg', 3), ('Vitamina C 1000mg', 2)], Decimal('20000'), Decimal('0')),
            (customers[1], [('Acetaminofén 500mg', 5), ('Gel Antibacterial', 1)], Decimal('15000'), Decimal('0')),
            (customers[2], [('Amoxicilina 500mg', 2)], Decimal('20000'), Decimal('5')),
            (customers[3], [('Vitamina D3 2000UI', 3), ('Crema Antifúngica', 1)], Decimal('30000'), Decimal('0')),
            (customers[4], [('Naproxeno 250mg', 4), ('Azitromicina 500mg', 1)], Decimal('30000'), Decimal('10')),
        ]

        for customer, items, amount_paid, tax_pct in sales_data:
            items_payload = [
                {'item_id': self.items[name].id, 'qty': qty}
                for name, qty in items
            ]
            try:
                service.execute(
                    customer_id=customer.id,
                    items=items_payload,
                    tax_percentage=tax_pct,
                    amount_paid=amount_paid,
                    user_id=admin.id,
                )
            except Exception as e:
                self.stdout.write(self.style.WARNING(f'  Sale skip: {e}'))

    # ------------------------------------------------------------------
    def _create_invoices(self):
        self.stdout.write('Creando facturas (invoice)...')
        invoices = [
            ('Juan Pérez',    '3119876543', 'Ibuprofeno 400mg',   2500, 3, 0),
            ('María López',   '3204561230', 'Vitamina C 1000mg',  4500, 2, 5000),
            ('Carlos Ramírez','3157890123', 'Amoxicilina 500mg',  8500, 1, 3000),
        ]
        for cname, cphone, item_name, price, qty, shipping in invoices:
            Invoice.objects.get_or_create(
                customer_name=cname,
                contact_number=cphone,
                item=self.items[item_name],
                defaults=dict(price_per_item=price, quantity=qty, shipping=shipping),
            )

    # ------------------------------------------------------------------
    def _create_bills(self):
        self.stdout.write('Creando cuentas por pagar (bills)...')
        bills = [
            ('Empresa de Energía',  3012345, 'admin@enel.com',   'Calle 1',  'Factura mayo 2026',      'Ref EE-2026-05',  350000, False),
            ('Acueducto Bogotá',    6012345, 'info@acuabog.com', 'Calle 2',  'Servicio acueducto',     'Ref AB-2026-05',  125000, True),
            ('PharmaCorp',          3001234, 'cobros@pharma.com','Calle 80', 'Orden compra OC-001',    'Transferencia',   900000, True),
            ('MediSuministros',     3109876, 'cxc@medi.com',     'Av Dorado','Reabastecimiento AB',    'Cheque #4421',    400000, False),
            ('Servicio de Internet',6054321, 'it@isp.com',       'Calle 5',  'Banda ancha mayo 2026',  'Débito automático', 89000, True),
        ]
        for inst, phone, email, addr, desc, pay, amount, status in bills:
            Bill.objects.get_or_create(
                institution_name=inst,
                amount=amount,
                defaults=dict(
                    phone_number=phone, email=email, address=addr,
                    description=desc, payment_details=pay, status=status,
                )
            )

    # ------------------------------------------------------------------
    def _create_deliveries(self):
        self.stdout.write('Creando entregas...')
        deliveries = [
            ('Ibuprofeno 400mg',   'Juan Pérez',    '3119876543', 'Calle 45 #12-30',   0,  True),
            ('Vitamina C 1000mg',  'María López',   '3204561230', 'Carrera 9 #18-05',  1,  False),
            ('Acetaminofén 500mg', 'Carlos Ramírez','3157890123', 'Av. 68 #30-15',     2,  False),
        ]
        for item_name, cname, phone, loc, day_offset, delivered in deliveries:
            Delivery.objects.get_or_create(
                customer_name=cname,
                item=self.items[item_name],
                defaults=dict(
                    phone_number=f'+57{phone}',
                    location=loc,
                    date=timezone.now() + timedelta(days=day_offset),
                    is_delivered=delivered,
                )
            )
