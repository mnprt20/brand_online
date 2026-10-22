from decimal import Decimal
from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models
from stores.managers import StoreScopedManager
from stores.models import Store


class Category(models.Model):
    store = models.ForeignKey(
        Store,
        on_delete=models.CASCADE,
        related_name='categories',
    )
    name = models.CharField(max_length=150)
    sort_order = models.IntegerField(default=0)

    objects = StoreScopedManager()

    class Meta:
        ordering = ['sort_order', 'name', 'id']
        verbose_name_plural = 'categories'

    def __str__(self):
        return self.name


class Product(models.Model):
    store = models.ForeignKey(
        Store,
        on_delete=models.CASCADE,
        related_name='products',
    )
    category = models.ForeignKey(
        Category,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='products',
    )
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True, default='')
    price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(Decimal('0.00'))],
    )
    image = models.ImageField(upload_to='products/', blank=True, null=True)
    stock = models.PositiveIntegerField(null=True, blank=True)
    is_available = models.BooleanField(default=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='created_products',
    )

    objects = StoreScopedManager()

    class Meta:
        ordering = ['name', 'id']

    def __str__(self):
        return self.name
