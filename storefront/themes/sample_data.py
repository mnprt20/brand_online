from decimal import Decimal


class SampleCategory:
    def __init__(self, pk, name, sort_order=0):
        self.pk = pk
        self.id = pk
        self.name = name
        self.sort_order = sort_order

    def __str__(self):
        return self.name


class SampleProduct:
    def __init__(self, pk, name, description, price, category, image=None, is_available=True):
        self.pk = pk
        self.id = pk
        self.name = name
        self.description = description
        self.price = Decimal(str(price))
        self.category = category
        self.image = image
        self.is_available = is_available
        self.stock = 25

    def __str__(self):
        return self.name


class SampleStore:
    def __init__(
        self,
        name='Atelier Botanica & Bakehouse',
        slug='sample-demo-store',
        description='Curated artisanal bakes, single-origin coffees, and small-batch pantry essentials.',
        template_key='classic',
        theme_color='#4f46e5',
        online_ordering_open=True,
        has_online=True,
    ):
        self.pk = 0
        self.id = 0
        self.name = name
        self.slug = slug
        self.description = description
        self.template_key = template_key
        self.theme_color = theme_color
        self.logo = None
        self.is_active = True
        self.online_ordering_open = online_ordering_open
        self.delivery_enabled = True
        self.pickup_enabled = True
        self.delivery_fee = Decimal('40.00')
        self.free_delivery_above = Decimal('500.00')
        self.minimum_order_amount = Decimal('150.00')
        self.delivery_note = 'Same-day local delivery within 6 km.'
        self.accept_upi_qr = True
        self.accept_cod = True
        self._has_online = has_online

    def has_online_features(self):
        return self._has_online

    def has_franchise_features(self):
        return True

    def __str__(self):
        return self.name


def build_sample_catalogue(theme_key='classic', brand_color='#4f46e5', selected_category_pk=None):
    cat_bakes = SampleCategory(1, 'Artisan Bakes', 1)
    cat_coffee = SampleCategory(2, 'Specialty Coffee', 2)
    cat_pantry = SampleCategory(3, 'Gourmet Pantry', 3)
    cat_gifts = SampleCategory(4, 'Gift Boxes', 4)
    categories = [cat_bakes, cat_coffee, cat_pantry, cat_gifts]

    all_products = [
        SampleProduct(
            101,
            'Sourdough Country Loaf',
            'Slow-fermented 36-hour organic wheat loaf with a caramelized blistered crust.',
            '240.00',
            cat_bakes,
        ),
        SampleProduct(
            102,
            'Cardamom Pistachio Kouign-Amann',
            'Flaky laminated pastry glazed with wildflower honey and roasted Iranian pistachios.',
            '195.00',
            cat_bakes,
        ),
        SampleProduct(
            103,
            'Single-Origin Chikmagalur Pour-Over',
            'Medium-light roast Arabica with notes of dark cacao, orange blossom, and toasted hazelnut.',
            '480.00',
            cat_coffee,
        ),
        SampleProduct(
            104,
            'Cold Brew Concentrate Bottle (500ml)',
            'Steeped for 18 hours in small batches; rich, velvety, and ready to pour over ice.',
            '360.00',
            cat_coffee,
        ),
        SampleProduct(
            105,
            'Smoked Sea Salt Almond Butter',
            'Stone-ground California almonds finished with flaky sea salt and Madagascar vanilla.',
            '550.00',
            cat_pantry,
        ),
        SampleProduct(
            106,
            'Weekend Brunch Hamper',
            'Includes sourdough loaf, cold brew concentrate, berry preserve, and two pastries.',
            '1250.00',
            cat_gifts,
        ),
    ]

    selected_category = None
    if selected_category_pk and str(selected_category_pk).isdigit():
        cat_id = int(selected_category_pk)
        for c in categories:
            if c.pk == cat_id:
                selected_category = c
                break

    if selected_category is not None:
        products = [p for p in all_products if p.category.pk == selected_category.pk]
    else:
        products = all_products

    sample_store = SampleStore(
        template_key=theme_key,
        theme_color=brand_color,
    )

    return {
        'store': sample_store,
        'categories': categories,
        'products': products,
        'selected_category': selected_category,
        'current_customer': None,
        'cart_items': [],
        'cart_total': Decimal('0.00'),
        'cart_count': 0,
        'is_demo': True,
    }
