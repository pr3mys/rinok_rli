import os
from flask import Flask, render_template, request, redirect, url_for, session, flash
from sqlalchemy import create_engine, event, func
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker, scoped_session
from werkzeug.security import generate_password_hash, check_password_hash
from dotenv import load_dotenv
from models import Base, Students, Shops, Goods, Orders, Purchases, Reviews, CATEGORIES

load_dotenv()

app = Flask(__name__)
app.config["SECRET_KEY"] = os.getenv("SECRET_KEY")
app.config.update(
    SESSION_COOKIE_SECURE=True,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
)


@event.listens_for(Engine, "connect")
def _pragma(conn, _):
    cur = conn.cursor()
    cur.execute("PRAGMA foreign_keys=ON")
    cur.close()


engine = create_engine("sqlite:///data_base.db", echo=False)
Base.metadata.create_all(engine)
db = scoped_session(sessionmaker(bind=engine))

ADMIN_LOGIN = os.getenv("ADMIN_LOGIN")
ADMIN_PASSWORD_HASH = generate_password_hash(os.getenv("ADMIN_PASSWORD") or "")
ADMIN_PHONES = [p.strip() for p in (os.getenv("ADMIN_PHONES") or "").split(",") if p.strip()]
ADMIN_PHONES_STR = ", ".join(ADMIN_PHONES) if ADMIN_PHONES else "—"

STATUS_LABELS = {
    "в корзине": "В корзине",
    "не оплачено": "Ожидает оплаты",
    "оплачено": "Ожидает подтверждения продавца",
    "средства получены": "Ожидает получения",
    "завершено": "Завершено",
}
STATUS_BADGES = {
    "в корзине": "secondary",
    "не оплачено": "warning",
    "оплачено": "info",
    "средства получены": "primary",
    "завершено": "success",
}


@app.teardown_appcontext
def _close(_=None):
    db.remove()


def is_admin():
    return session.get("user_type") == "admin"


def me():
    if session.get("user_type") != "student":
        return None
    return db.query(Students).filter_by(id=session["student_id"]).first()


def buy_error(s):
    if s.verification != 1:
        return f"Аккаунт не верифицирован. Для покупок обратитесь к администраторам: {ADMIN_PHONES_STR}"
    if s.banned_buy:
        return f"Вам запрещено покупать. Обратитесь к администраторам: {ADMIN_PHONES_STR}"
    return None


def sell_error(s):
    if s.verification != 1:
        return f"Аккаунт не верифицирован. Для продажи обратитесь к администраторам: {ADMIN_PHONES_STR}"
    if s.banned_sell:
        return f"Вам запрещено продавать. Обратитесь к администраторам: {ADMIN_PHONES_STR}"
    return None


def recalc_rating(shop_id):
    avg = db.query(func.avg(Reviews.rating)).filter(Reviews.shop_id == shop_id).scalar()
    shop = db.query(Shops).filter_by(id=shop_id).first()
    if shop:
        shop.rating = round(float(avg), 2) if avg else 0.0


@app.context_processor
def globals_():
    cart_count = 0
    has_shop = False
    if session.get("user_type") == "student":
        sid = session["student_id"]
        cart_count = db.query(Orders).filter_by(student_id=sid, status="в корзине").count()
        has_shop = db.query(Shops.id).filter_by(student_id=sid).first() is not None
    return {
        "cart_count": cart_count,
        "has_shop": has_shop,
        "categories": CATEGORIES,
        "ADMIN_PHONES": ADMIN_PHONES,
        "ADMIN_PHONES_STR": ADMIN_PHONES_STR,
        "STATUS_LABELS": STATUS_LABELS,
        "STATUS_BADGES": STATUS_BADGES,
        "is_admin": is_admin(),
    }


@app.route("/")
def main():
    if "user_type" not in session:
        return render_template("main.html")
    if is_admin():
        return redirect(url_for("admin_panel"))
    return redirect(url_for("showcase"))


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        login_ = request.form["username"].strip()
        password = request.form["password"]

        if login_ == ADMIN_LOGIN and check_password_hash(ADMIN_PASSWORD_HASH, password):
            session.clear()
            session.update(user_type="admin", username="Администратор")
            return redirect(url_for("main"))

        s = db.query(Students).filter_by(login=login_).first()
        if s and check_password_hash(s.password, password):
            session.clear()
            session.update(user_type="student", student_id=s.id, username=s.login)
            return redirect(url_for("main"))

        return render_template("login.html", error="Неверный логин или пароль")
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("main"))


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        login_ = request.form["username"].strip()
        p1 = request.form["password1"]
        p2 = request.form["password2"]
        first = request.form["first_name"].strip()
        last = request.form["last_name"].strip()
        phone = request.form["phone_number"].strip()
        cls = request.form.get("class_name", "").strip() or None

        if not phone:
            return render_template("register.html", error="Укажите номер телефона")
        if p1 != p2:
            return render_template("register.html", error="Пароли не совпадают")
        if db.query(Students).filter_by(login=login_).first():
            return render_template("register.html", error="Пользователь с таким логином уже существует")
        if db.query(Students).filter_by(phone_number=phone).first():
            return render_template("register.html", error="На этот номер уже зарегистрирован аккаунт")

        db.add(Students(
            login=login_, password=generate_password_hash(p1),
            first_name=first, last_name=last, phone_number=phone,
            class_name=cls, verification=0,
        ))
        db.commit()
        return redirect(url_for("login"))
    return render_template("register.html")


@app.route("/showcase")
def showcase():
    if not (is_admin() or me()):
        return redirect(url_for("login"))

    category = request.args.get("category", "все")
    q = db.query(Goods).join(Shops).join(Students).filter(Goods.is_active == True)
    if not is_admin():
        q = q.filter(Goods.quantity > 0, Students.verification == 1, Students.banned_sell == False)
    if category in CATEGORIES:
        q = q.filter(Goods.category == category)
    else:
        category = "все"
    return render_template("showcase.html", goods_list=q.all(), category=category)


@app.route("/shop/<int:shop_id>")
def shop_page(shop_id):
    if not (is_admin() or me()):
        return redirect(url_for("login"))

    shop = db.query(Shops).filter_by(id=shop_id).first()
    if not shop:
        flash("Магазин не найден", "warning")
        return redirect(url_for("showcase"))

    if not is_admin() and (shop.owner.verification != 1 or shop.owner.banned_sell):
        flash("Магазин временно недоступен", "warning")
        return redirect(url_for("showcase"))

    goods = db.query(Goods).filter_by(shop_id=shop.id, is_active=True).all()
    reviews = db.query(Reviews).filter_by(shop_id=shop.id).order_by(Reviews.created_at.desc()).all()
    return render_template("shop.html", shop=shop, goods_list=goods, reviews=reviews)


@app.route("/cart")
def cart():
    s = me()
    if not s:
        return redirect(url_for("login"))

    items = db.query(Orders).filter_by(student_id=s.id, status="в корзине").order_by(Orders.created_at.asc()).all()
    shop = db.query(Shops).filter_by(id=items[0].shop_id).first() if items else None
    subtotal = sum(o.price_at_purchase * o.quantity for o in items) if items else 0.0
    err = buy_error(s)
    return render_template("cart.html", cart_items=items, shop=shop, subtotal=subtotal,
                           can_checkout=err is None, buy_error=err)


@app.route("/cart/add/<int:goods_id>", methods=["POST"])
def cart_add(goods_id):
    s = me()
    if not s:
        return redirect(url_for("login"))

    g = db.query(Goods).filter_by(id=goods_id).first()
    if not g or not g.is_active:
        flash("Товар недоступен", "danger")
        return redirect(url_for("showcase"))
    if g.shop.owner.verification != 1 or g.shop.owner.banned_sell:
        flash("Магазин временно недоступен", "warning")
        return redirect(url_for("showcase"))
    if g.shop.student_id == s.id:
        flash("Нельзя купить товар в своём магазине", "warning")
        return redirect(url_for("shop_page", shop_id=g.shop_id))

    try:
        qty = max(1, int(request.form.get("quantity", 1)))
    except (TypeError, ValueError):
        qty = 1

    if qty > g.quantity:
        flash("Недостаточно товара", "danger")
        return redirect(url_for("shop_page", shop_id=g.shop_id))

    cart_items = db.query(Orders).filter_by(student_id=s.id, status="в корзине").all()
    if cart_items and any(o.shop_id != g.shop_id for o in cart_items):
        flash("В корзине уже есть товары другого продавца", "warning")
        return redirect(url_for("shop_page", shop_id=g.shop_id))

    existing = db.query(Orders).filter_by(student_id=s.id, goods_id=g.id, status="в корзине").first()
    if existing:
        if existing.quantity + qty > g.quantity:
            flash("Недостаточно товара", "danger")
            return redirect(url_for("shop_page", shop_id=g.shop_id))
        existing.quantity += qty
    else:
        db.add(Orders(student_id=s.id, goods_id=g.id, shop_id=g.shop_id,
                      quantity=qty, price_at_purchase=g.price, status="в корзине"))
    db.commit()
    flash("Добавлено в корзину", "success")
    return redirect(url_for("shop_page", shop_id=g.shop_id))


@app.route("/cart/remove/<int:order_id>", methods=["POST"])
def cart_remove(order_id):
    s = me()
    if not s:
        return redirect(url_for("login"))
    o = db.query(Orders).filter_by(id=order_id, student_id=s.id, status="в корзине").first()
    if o:
        db.delete(o)
        db.commit()
    return redirect(url_for("cart"))


@app.route("/cart/buy", methods=["POST"])
def cart_buy():
    s = me()
    if not s:
        return redirect(url_for("login"))
    err = buy_error(s)
    if err:
        flash(err, "warning")
        return redirect(url_for("cart"))

    items = db.query(Orders).filter_by(student_id=s.id, status="в корзине").all()
    if not items:
        return redirect(url_for("cart"))

    shop = db.query(Shops).filter_by(id=items[0].shop_id).first()
    if not shop or shop.owner.verification != 1 or shop.owner.banned_sell:
        flash("Магазин временно недоступен", "warning")
        return redirect(url_for("cart"))
    if shop.student_id == s.id:
        flash("В корзине есть товары из вашего магазина. Удалите их, чтобы оформить бронь.", "warning")
        return redirect(url_for("cart"))

    dtype = request.form.get("delivery_type", "pickup")
    if dtype not in ("pickup", "delivery"):
        dtype = "pickup"

    dcab = dtime = None
    dprice = 0.0
    if dtype == "delivery":
        dcab = request.form.get("delivery_cabinet", "").strip()
        dtime = request.form.get("delivery_time", "").strip()
        if not dcab or not dtime:
            flash("Укажите кабинет и время доставки", "danger")
            return redirect(url_for("cart"))
        dprice = shop.delivery_price or 0.0

    for o in items:
        g = db.query(Goods).filter_by(id=o.goods_id).first()
        if not g or g.quantity < o.quantity:
            flash(f"Недостаточно товара: {g.name if g else '?'}", "danger")
            return redirect(url_for("cart"))
        if g.max_bron is not None:
            already = db.query(func.coalesce(func.sum(Orders.quantity), 0)).filter(
                Orders.student_id == s.id, Orders.goods_id == g.id,
                Orders.status.in_(("не оплачено", "оплачено")),
            ).scalar()
            if already + o.quantity > g.max_bron:
                flash(f"Лимит брони для «{g.name}» — {g.max_bron} шт.", "warning")
                return redirect(url_for("cart"))

    p = Purchases(student_id=s.id, shop_id=shop.id, delivery_type=dtype,
                  delivery_cabinet=dcab, delivery_time=dtime, delivery_price=dprice)
    db.add(p)
    db.flush()

    for o in items:
        g = db.query(Goods).filter_by(id=o.goods_id).first()
        g.quantity -= o.quantity
        g.bron_sum += o.quantity
        o.purchase_id = p.id
        o.status = "не оплачено"

    db.commit()
    flash("Бронь оформлена. Переведите деньги продавцу и подтвердите оплату.", "success")
    return redirect(url_for("profile"))


@app.route("/purchase/<int:purchase_id>/pay", methods=["POST"])
def purchase_pay(purchase_id):
    s = me()
    if not s:
        return redirect(url_for("login"))

    p = db.query(Purchases).filter_by(id=purchase_id, student_id=s.id).first()
    if not p:
        flash("Заказ не найден", "danger")
        return redirect(url_for("profile"))

    orders = [o for o in p.orders if o.status == "не оплачено"]
    if not orders:
        flash("Нет заказов, ожидающих оплаты", "warning")
        return redirect(url_for("profile"))

    for o in orders:
        o.status = "оплачено"
    db.commit()
    flash("Оплата подтверждена. Ожидайте проверки продавца.", "success")
    return redirect(url_for("profile"))


@app.route("/purchase/<int:purchase_id>/cancel", methods=["POST"])
def purchase_cancel(purchase_id):
    s = me()
    if not s:
        return redirect(url_for("login"))

    p = db.query(Purchases).filter_by(id=purchase_id, student_id=s.id).first()
    if not p:
        flash("Заказ не найден", "danger")
        return redirect(url_for("profile"))
    if p.status != "не оплачено":
        flash("Отменить можно только на этапе оплаты", "warning")
        return redirect(url_for("profile"))

    for o in p.orders:
        g = db.query(Goods).filter_by(id=o.goods_id).first()
        if g:
            g.quantity += o.quantity
            g.bron_sum -= o.quantity
    db.delete(p)
    db.commit()
    flash("Бронь отменена. Товары вернулись в продажу.", "success")
    return redirect(url_for("profile"))


@app.route("/purchase/<int:purchase_id>/receive_funds", methods=["POST"])
def purchase_receive_funds(purchase_id):
    s = me()
    if not s:
        return redirect(url_for("login"))

    shop = db.query(Shops).filter_by(student_id=s.id).first()
    if not shop:
        return redirect(url_for("profile"))

    p = db.query(Purchases).filter_by(id=purchase_id, shop_id=shop.id).first()
    if not p:
        flash("Заказ не найден", "danger")
        return redirect(url_for("my_shop"))

    orders = [o for o in p.orders if o.status == "оплачено"]
    if not orders:
        flash("Нет заказов, ожидающих подтверждения", "warning")
        return redirect(url_for("my_shop"))

    for o in orders:
        g = db.query(Goods).filter_by(id=o.goods_id).first()
        if g:
            g.bron_sum -= o.quantity
        o.status = "средства получены"
    db.commit()
    flash("Средства подтверждены", "success")
    return redirect(url_for("my_shop"))


@app.route("/purchase/<int:purchase_id>/receive_goods", methods=["POST"])
def purchase_receive_goods(purchase_id):
    s = me()
    if not s:
        return redirect(url_for("login"))

    p = db.query(Purchases).filter_by(id=purchase_id, student_id=s.id).first()
    if not p:
        flash("Заказ не найден", "danger")
        return redirect(url_for("profile"))

    orders = [o for o in p.orders if o.status == "средства получены"]
    if not orders:
        flash("Нет заказов, ожидающих получения", "warning")
        return redirect(url_for("profile"))

    for o in orders:
        o.status = "завершено"
    db.commit()
    flash("Заказ получен", "success")
    return redirect(url_for("profile"))


@app.route("/purchase/<int:purchase_id>/review", methods=["POST"])
def purchase_review(purchase_id):
    s = me()
    if not s:
        return redirect(url_for("login"))

    p = db.query(Purchases).filter_by(id=purchase_id, student_id=s.id).first()
    if not p or p.status != "завершено" or p.review:
        flash("Отзыв недоступен", "warning")
        return redirect(url_for("profile"))

    try:
        rating = int(request.form.get("rating", 5))
    except (TypeError, ValueError):
        rating = 5
    rating = max(1, min(5, rating))

    db.add(Reviews(
        purchase_id=p.id, student_id=s.id, shop_id=p.shop_id,
        rating=rating, comment=request.form.get("comment", "").strip() or None,
    ))
    db.commit()
    recalc_rating(p.shop_id)
    db.commit()
    flash("Спасибо за отзыв", "success")
    return redirect(url_for("profile"))


@app.route("/profile")
def profile():
    s = me()
    if not s:
        return redirect(url_for("login"))

    purchases = db.query(Purchases).filter_by(student_id=s.id).order_by(Purchases.created_at.desc()).all()
    return render_template("profile.html", student=s, my_purchases=purchases,
                           buy_error=buy_error(s), sell_error=sell_error(s))


@app.route("/profile/edit", methods=["POST"])
def profile_edit():
    s = me()
    if not s:
        return redirect(url_for("login"))

    if s.verification == 1:
        flash("Данные верифицированного аккаунта меняет только администратор", "warning")
        return redirect(url_for("profile"))

    first = request.form.get("first_name", "").strip()
    last = request.form.get("last_name", "").strip()
    phone = request.form.get("phone_number", "").strip()
    cls = request.form.get("class_name", "").strip() or None

    if not first or not last or not phone:
        flash("Заполните обязательные поля", "danger")
        return redirect(url_for("profile"))

    if phone != s.phone_number and db.query(Students).filter_by(phone_number=phone).first():
        flash("Этот номер уже используется", "danger")
        return redirect(url_for("profile"))

    s.first_name = first
    s.last_name = last
    s.phone_number = phone
    s.class_name = cls
    db.commit()
    flash("Данные обновлены", "success")
    return redirect(url_for("profile"))


@app.route("/profile/password", methods=["POST"])
def profile_password():
    s = me()
    if not s:
        return redirect(url_for("login"))

    old = request.form.get("old_password", "")
    new1 = request.form.get("new_password", "")
    new2 = request.form.get("new_password2", "")

    if not check_password_hash(s.password, old):
        flash("Неверный текущий пароль", "danger")
    elif len(new1) < 6:
        flash("Пароль должен быть не менее 6 символов", "danger")
    elif new1 != new2:
        flash("Пароли не совпадают", "danger")
    else:
        s.password = generate_password_hash(new1)
        db.commit()
        flash("Пароль изменён", "success")
    return redirect(url_for("profile"))


@app.route("/my-shop")
def my_shop():
    s = me()
    if not s:
        return redirect(url_for("login"))

    shop = db.query(Shops).filter_by(student_id=s.id).first()
    if not shop:
        return redirect(url_for("profile"))

    goods = db.query(Goods).filter_by(shop_id=shop.id).order_by(Goods.id.desc()).all()
    purchases = db.query(Purchases).filter_by(shop_id=shop.id).order_by(Purchases.created_at.desc()).all()
    grouped = {"не оплачено": [], "оплачено": [], "средства получены": [], "завершено": []}
    for p in purchases:
        if p.status in grouped:
            grouped[p.status].append(p)

    return render_template("my_shop.html", student=s, shop=shop, shop_goods=goods,
                           grouped=grouped, sell_error=sell_error(s))


@app.route("/shop/create", methods=["POST"])
def shop_create():
    s = me()
    if not s:
        return redirect(url_for("login"))
    err = sell_error(s)
    if err:
        flash(err, "warning")
        return redirect(url_for("profile"))

    if s.shop:
        flash("У вас уже есть магазин", "warning")
        return redirect(url_for("my_shop"))

    name = request.form.get("name", "").strip()
    if not name:
        flash("Введите название", "danger")
        return redirect(url_for("profile"))

    try:
        dprice = max(0.0, float(request.form.get("delivery_price", 0) or 0))
    except ValueError:
        dprice = 0.0

    db.add(Shops(
        student_id=s.id, name=name,
        description=request.form.get("description", "").strip() or None,
        bank=request.form.get("bank", "").strip() or None,
        payment_number=request.form.get("payment_number", "").strip() or None,
        cabinet=request.form.get("cabinet", "").strip() or None,
        delivery_price=dprice,
    ))
    db.commit()
    flash("Магазин создан", "success")
    return redirect(url_for("my_shop"))


@app.route("/shop/edit", methods=["POST"])
def shop_edit():
    s = me()
    if not s:
        return redirect(url_for("login"))
    err = sell_error(s)
    if err:
        flash(err, "warning")
        return redirect(url_for("my_shop"))

    shop = db.query(Shops).filter_by(student_id=s.id).first()
    if not shop:
        return redirect(url_for("profile"))

    name = request.form.get("name", "").strip()
    if not name:
        flash("Введите название", "danger")
        return redirect(url_for("my_shop"))

    try:
        dprice = max(0.0, float(request.form.get("delivery_price", 0) or 0))
    except ValueError:
        dprice = 0.0

    shop.name = name
    shop.description = request.form.get("description", "").strip() or None
    shop.bank = request.form.get("bank", "").strip() or None
    shop.payment_number = request.form.get("payment_number", "").strip() or None
    shop.cabinet = request.form.get("cabinet", "").strip() or None
    shop.delivery_price = dprice
    db.commit()
    flash("Магазин обновлён", "success")
    return redirect(url_for("my_shop"))


def read_goods_form():
    name = request.form.get("name", "").strip()
    cat = request.form.get("category", "").strip()
    if not name or cat not in CATEGORIES:
        return None, "Проверьте название и категорию"
    try:
        price = float(request.form.get("price", 0))
        qty = int(request.form.get("quantity", 0))
    except (TypeError, ValueError):
        return None, "Некорректная цена или количество"
    if price < 0 or qty < 0:
        return None, "Цена и количество не могут быть отрицательными"

    raw = request.form.get("max_bron", "").strip()
    max_bron = None
    if raw:
        try:
            max_bron = int(raw)
            if max_bron < 0:
                return None, "Некорректный лимит брони"
        except ValueError:
            return None, "Некорректный лимит брони"

    return {
        "name": name, "category": cat, "price": price, "quantity": qty,
        "max_bron": max_bron,
        "description": request.form.get("description", "").strip() or None,
    }, None


@app.route("/goods/add", methods=["POST"])
def goods_add():
    s = me()
    if not s:
        return redirect(url_for("login"))
    err = sell_error(s)
    if err:
        flash(err, "warning")
        return redirect(url_for("my_shop"))

    shop = db.query(Shops).filter_by(student_id=s.id).first()
    if not shop:
        return redirect(url_for("profile"))

    data, err = read_goods_form()
    if err:
        flash(err, "danger")
        return redirect(url_for("my_shop"))

    db.add(Goods(shop_id=shop.id, bron_sum=0, is_active=True, **data))
    db.commit()
    flash("Товар добавлен", "success")
    return redirect(url_for("my_shop"))


@app.route("/goods/<int:goods_id>/edit", methods=["POST"])
def goods_edit(goods_id):
    s = me()
    if not s:
        return redirect(url_for("login"))
    err = sell_error(s)
    if err:
        flash(err, "warning")
        return redirect(url_for("my_shop"))

    shop = db.query(Shops).filter_by(student_id=s.id).first()
    if not shop:
        return redirect(url_for("profile"))

    g = db.query(Goods).filter_by(id=goods_id, shop_id=shop.id).first()
    if not g:
        flash("Товар не найден", "danger")
        return redirect(url_for("my_shop"))

    data, err = read_goods_form()
    if err:
        flash(err, "danger")
        return redirect(url_for("my_shop"))

    for k, v in data.items():
        setattr(g, k, v)
    db.commit()
    flash("Товар обновлён", "success")
    return redirect(url_for("my_shop"))


@app.route("/goods/<int:goods_id>/toggle", methods=["POST"])
def goods_toggle(goods_id):
    s = me()
    if not s:
        return redirect(url_for("login"))
    err = sell_error(s)
    if err:
        flash(err, "warning")
        return redirect(url_for("my_shop"))

    shop = db.query(Shops).filter_by(student_id=s.id).first()
    if not shop:
        return redirect(url_for("profile"))

    g = db.query(Goods).filter_by(id=goods_id, shop_id=shop.id).first()
    if g:
        g.is_active = not g.is_active
        db.commit()
    return redirect(url_for("my_shop"))


@app.route("/goods/<int:goods_id>/delete", methods=["POST"])
def goods_delete(goods_id):
    s = me()
    if not s:
        return redirect(url_for("login"))
    err = sell_error(s)
    if err:
        flash(err, "warning")
        return redirect(url_for("my_shop"))

    shop = db.query(Shops).filter_by(student_id=s.id).first()
    if not shop:
        return redirect(url_for("profile"))

    g = db.query(Goods).filter_by(id=goods_id, shop_id=shop.id).first()
    if not g:
        return redirect(url_for("my_shop"))

    active = db.query(Orders).filter(
        Orders.goods_id == g.id,
        Orders.status.in_(("не оплачено", "оплачено", "средства получены")),
    ).count()
    if active:
        flash("Нельзя удалить товар с активными бронями", "danger")
        return redirect(url_for("my_shop"))

    db.delete(g)
    db.commit()
    flash("Товар удалён", "success")
    return redirect(url_for("my_shop"))


@app.route("/admin")
def admin_panel():
    if not is_admin():
        return redirect(url_for("login"))
    students = db.query(Students).order_by(Students.id.asc()).all()
    return render_template("admin.html", students=students)


@app.route("/admin/user/<int:user_id>", methods=["GET", "POST"])
def admin_user(user_id):
    if not is_admin():
        return redirect(url_for("login"))
    s = db.query(Students).filter_by(id=user_id).first()
    if not s:
        return redirect(url_for("admin_panel"))

    if request.method == "POST":
        login_ = request.form.get("login", "").strip()
        first = request.form.get("first_name", "").strip()
        last = request.form.get("last_name", "").strip()
        phone = request.form.get("phone_number", "").strip()
        cls = request.form.get("class_name", "").strip() or None

        if not login_ or not first or not last or not phone:
            flash("Заполните обязательные поля", "danger")
        elif login_ != s.login and db.query(Students).filter_by(login=login_).first():
            flash("Логин занят", "danger")
        elif phone != s.phone_number and db.query(Students).filter_by(phone_number=phone).first():
            flash("Телефон занят", "danger")
        else:
            s.login = login_
            s.first_name = first
            s.last_name = last
            s.phone_number = phone
            s.class_name = cls
            db.commit()
            flash("Сохранено", "success")
            return redirect(url_for("admin_panel"))

    return render_template("admin_user.html", student=s)


def _pick(user_id):
    if not is_admin():
        return None
    return db.query(Students).filter_by(id=user_id).first()


@app.route("/admin/user/<int:user_id>/verify", methods=["POST"])
def admin_verify(user_id):
    s = _pick(user_id)
    if s:
        s.verification = 1
        db.commit()
    return redirect(request.referrer or url_for("admin_panel"))


@app.route("/admin/user/<int:user_id>/unverify", methods=["POST"])
def admin_unverify(user_id):
    s = _pick(user_id)
    if s:
        s.verification = 0
        db.commit()
    return redirect(request.referrer or url_for("admin_panel"))


@app.route("/admin/user/<int:user_id>/ban_sell", methods=["POST"])
def admin_ban_sell(user_id):
    s = _pick(user_id)
    if s:
        s.banned_sell = True
        db.commit()
    return redirect(request.referrer or url_for("admin_panel"))


@app.route("/admin/user/<int:user_id>/unban_sell", methods=["POST"])
def admin_unban_sell(user_id):
    s = _pick(user_id)
    if s:
        s.banned_sell = False
        db.commit()
    return redirect(request.referrer or url_for("admin_panel"))


@app.route("/admin/user/<int:user_id>/ban_buy", methods=["POST"])
def admin_ban_buy(user_id):
    s = _pick(user_id)
    if s:
        s.banned_buy = True
        db.commit()
    return redirect(request.referrer or url_for("admin_panel"))


@app.route("/admin/user/<int:user_id>/unban_buy", methods=["POST"])
def admin_unban_buy(user_id):
    s = _pick(user_id)
    if s:
        s.banned_buy = False
        db.commit()
    return redirect(request.referrer or url_for("admin_panel"))


if __name__ == "__main__":
    app.run(port=8080, host="127.0.0.1", debug=True)