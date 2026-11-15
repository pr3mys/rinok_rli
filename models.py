from datetime import datetime
from sqlalchemy import (Column, Integer, String, Text, Float, Boolean, DateTime, ForeignKey, CheckConstraint, UniqueConstraint,)
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()

CATEGORIES = ("еда", "услуги", "канцелярия", "другое")
ORDER_STATUSES = ("в корзине", "не оплачено", "оплачено", "средства получены", "завершено")


class Students(Base):
    __tablename__ = "students"

    id = Column(Integer, primary_key=True)
    login = Column(String(100), unique=True, nullable=False)
    password = Column(String(300), nullable=False)
    first_name = Column(String(100), nullable=False)
    last_name = Column(String(100), nullable=False)
    phone_number = Column(String(20), unique=True, nullable=False)
    verification = Column(Integer, nullable=False, default=0)
    class_name = Column(String(20))
    banned_sell = Column(Boolean, nullable=False, default=False)
    banned_buy = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    shop = relationship("Shops", back_populates="owner", uselist=False, cascade="all, delete-orphan")
    orders = relationship("Orders", back_populates="student", cascade="all, delete-orphan")
    purchases = relationship("Purchases", back_populates="student", cascade="all, delete-orphan")
    reviews = relationship("Reviews", back_populates="student", cascade="all, delete-orphan")


class Shops(Base):
    __tablename__ = "shops"

    id = Column(Integer, primary_key=True)
    student_id = Column(Integer, ForeignKey("students.id", ondelete="CASCADE"), nullable=False)
    name = Column(String(150), nullable=False)
    description = Column(Text)
    rating = Column(Float, nullable=False, default=0.0)
    bank = Column(String(100))
    payment_number = Column(String(100))
    cabinet = Column(String(20))
    delivery_price = Column(Float, nullable=False, default=0.0)

    __table_args__ = (
        UniqueConstraint("student_id", name="uq_shops_student_id"),
        CheckConstraint("rating >= 0", name="ck_shops_rating_nonneg"),
        CheckConstraint("delivery_price >= 0", name="ck_shops_delivery_price_nonneg"),
    )

    owner = relationship("Students", back_populates="shop")
    goods = relationship("Goods", back_populates="shop", cascade="all, delete-orphan")
    orders = relationship("Orders", back_populates="shop", cascade="all, delete-orphan")
    purchases = relationship("Purchases", back_populates="shop", cascade="all, delete-orphan")
    reviews = relationship("Reviews", back_populates="shop", cascade="all, delete-orphan")


class Goods(Base):
    __tablename__ = "goods"

    id = Column(Integer, primary_key=True)
    shop_id = Column(Integer, ForeignKey("shops.id", ondelete="CASCADE"), nullable=False)
    name = Column(String(200), nullable=False)
    description = Column(Text)
    category = Column(String(20), nullable=False)
    price = Column(Float, nullable=False)
    quantity = Column(Integer, nullable=False, default=0)
    bron_sum = Column(Integer, nullable=False, default=0)
    max_bron = Column(Integer)
    is_active = Column(Boolean, nullable=False, default=True)

    __table_args__ = (
        CheckConstraint("category IN ('еда','услуги','канцелярия','другое')", name="ck_goods_category"),
        CheckConstraint("price >= 0", name="ck_goods_price_nonneg"),
        CheckConstraint("quantity >= 0", name="ck_goods_qty_nonneg"),
        CheckConstraint("bron_sum >= 0", name="ck_goods_bron_nonneg"),
        CheckConstraint("max_bron IS NULL OR max_bron >= 0", name="ck_goods_max_bron_nonneg"),
    )

    shop = relationship("Shops", back_populates="goods")
    orders = relationship("Orders", back_populates="goods", cascade="all, delete-orphan")


class Purchases(Base):
    __tablename__ = "purchases"

    id = Column(Integer, primary_key=True)
    student_id = Column(Integer, ForeignKey("students.id", ondelete="CASCADE"), nullable=False)
    shop_id = Column(Integer, ForeignKey("shops.id", ondelete="CASCADE"), nullable=False)
    delivery_type = Column(String(20), nullable=False, default="pickup")
    delivery_cabinet = Column(String(20))
    delivery_time = Column(String(100))
    delivery_price = Column(Float, nullable=False, default=0.0)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        CheckConstraint("delivery_type IN ('pickup','delivery')", name="ck_purchases_delivery_type"),
        CheckConstraint("delivery_price >= 0", name="ck_purchases_delivery_price_nonneg"),
    )

    student = relationship("Students", back_populates="purchases")
    shop = relationship("Shops", back_populates="purchases")
    orders = relationship("Orders", back_populates="purchase", cascade="all, delete-orphan")
    review = relationship("Reviews", back_populates="purchase", uselist=False, cascade="all, delete-orphan")

    @property
    def products_total(self):
        return sum(o.price_at_purchase * o.quantity for o in self.orders)
    @property
    def total(self):
        return self.products_total + self.delivery_price
    @property
    def status(self):
        return self.orders[0].status if self.orders else None


class Orders(Base):
    __tablename__ = "orders"

    id = Column(Integer, primary_key=True)
    student_id = Column(Integer, ForeignKey("students.id", ondelete="CASCADE"), nullable=False)
    goods_id = Column(Integer, ForeignKey("goods.id", ondelete="CASCADE"), nullable=False)
    shop_id = Column(Integer, ForeignKey("shops.id", ondelete="CASCADE"), nullable=False)
    purchase_id = Column(Integer, ForeignKey("purchases.id", ondelete="CASCADE"))
    quantity = Column(Integer, nullable=False, default=1)
    price_at_purchase = Column(Float, nullable=False)
    status = Column(String(30), nullable=False, default="в корзине")
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    __table_args__ = (
        CheckConstraint(
            "status IN ('в корзине','не оплачено','оплачено','средства получены','завершено')",
            name="ck_orders_status",
        ),
        CheckConstraint("quantity > 0", name="ck_orders_qty_pos"),
        CheckConstraint("price_at_purchase >= 0", name="ck_orders_price_nonneg"),
    )

    student = relationship("Students", back_populates="orders")
    goods = relationship("Goods", back_populates="orders")
    shop = relationship("Shops", back_populates="orders")
    purchase = relationship("Purchases", back_populates="orders")


class Reviews(Base):
    __tablename__ = "reviews"

    id = Column(Integer, primary_key=True)
    purchase_id = Column(Integer, ForeignKey("purchases.id", ondelete="CASCADE"), unique=True, nullable=False)
    student_id = Column(Integer, ForeignKey("students.id", ondelete="CASCADE"), nullable=False)
    shop_id = Column(Integer, ForeignKey("shops.id", ondelete="CASCADE"), nullable=False)
    rating = Column(Integer, nullable=False)
    comment = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        CheckConstraint("rating >= 1 AND rating <= 5", name="ck_reviews_rating"),
    )

    purchase = relationship("Purchases", back_populates="review")
    student = relationship("Students", back_populates="reviews")
    shop = relationship("Shops", back_populates="reviews")