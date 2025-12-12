#!/usr/bin/env python
# -*- coding: utf-8 -*-

import sqlite3
import os
import secrets
from datetime import datetime
from types import SimpleNamespace

from flask import (
    Flask, render_template, request, redirect,
    url_for, g, session, abort
)

# ============================================
# إعدادات أساسية + خيارات الفورم
# ============================================

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
DB_PATH = os.path.join(BASE_DIR, "approval_requests.db")

app = Flask(__name__)
# IMPORTANT: غيّر السر قبل تشغيله على سيرفر حقيقي
app.config["SECRET_KEY"] = "CHANGE_THIS_SECRET_KEY_123"
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

# كلمات سر المديرين (يفضل لاحقاً من Environment Variables)
MANAGER1_PASSWORD = "manager1"
MANAGER2_PASSWORD = "manager2"

# مستخدم مشاهدة فقط (Admin Viewer)
VIEWER_USERNAME = "viewer"
VIEWER_PASSWORD = "viewer123"


# نضيف هذا
MANAGER_PASSWORDS = {
    1: MANAGER1_PASSWORD,
    2: MANAGER2_PASSWORD
}



# Project / Unit options (عدّلهم كما تريد)
PROJECT_CHOICES = [
    "Project A",
    "Project B",
    "Project C",
    "Project D",
]

# هنا مثلاً من 1 إلى 300، عدّل حسب نظامك
UNIT_CHOICES = [str(i) for i in range(1, 301)]


# ============================================
# قاعدة البيانات
# ============================================

def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH, check_same_thread=False)
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(exception):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    db = get_db()
    cur = db.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS requests (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        created_at TEXT,
        updated_at TEXT,
        status TEXT,            -- Pending L1, Pending L2, Approved, Rejected
        current_step INTEGER,   -- 1, 2, 0
        edit_token TEXT,

        project_name TEXT,
        unit_number TEXT,
        paid_amount TEXT,
        buyer_name TEXT,
        agent_name TEXT,
        agency_name TEXT,
        agent_contact TEXT,

        price_reduction_selected INTEGER,
        bulk_discount_selected INTEGER,
        change_payment_plan_selected INTEGER,
        unit_switch_selected INTEGER,
        unit_cancellation_selected INTEGER,
        refund_selected INTEGER,
        late_payment_selected INTEGER,
        waiver_late_fee_selected INTEGER,
        issuance_spa_selected INTEGER,
        registration_dld_selected INTEGER,
        others_selected INTEGER,

        pr_listed_price TEXT,
        pr_discount_amount TEXT,
        pr_selling_price TEXT,
        pr_discount_percent TEXT,

        bd_listed_price TEXT,
        bd_discount_amount TEXT,
        bd_selling_price TEXT,
        bd_discount_percent TEXT,
        bd_units TEXT,

        cpp_down_payment_percent TEXT,
        cpp_down_payment_date TEXT,
        cpp_2nd_payment_percent TEXT,
        cpp_2nd_payment_date TEXT,
        cpp_3rd_payment_percent TEXT,
        cpp_3rd_payment_date TEXT,
        cpp_4th_payment_percent TEXT,
        cpp_4th_payment_date TEXT,
        cpp_5th_payment_percent TEXT,
        cpp_5th_payment_date TEXT,
        cpp_6th_payment_percent TEXT,
        cpp_6th_payment_date TEXT,
        cpp_completion_percent TEXT,
        cpp_completion_date TEXT,

        us_booked_unit TEXT,
        us_new_unit TEXT,
        us_new_unit_selling_price TEXT,

        uc_amount_paid TEXT,

        rf_booking_fees_amount TEXT,
        rf_payment_amount TEXT,
        rf_refund_amount TEXT,

        lp_payment_schedule_no TEXT,
        lp_initial_due_date TEXT,
        lp_new_payment_date TEXT,
        lp_penalty_amount TEXT,
        lp_overdue_period TEXT,

        wl_downpayment_spa_date TEXT,
        wl_2nd_payment_spa_date TEXT,
        wl_3rd_payment_spa_date TEXT,
        wl_4th_payment_spa_date TEXT,
        wl_5th_payment_spa_date TEXT,
        wl_6th_payment_spa_date TEXT,

        wl_penalty_amount TEXT,
        wl_waiver_amount TEXT,

        spa_down_payment_received TEXT,
        spa_percent TEXT,

        dld_down_payment_received TEXT,
        dld_percent TEXT,

        others_text TEXT,

        doc_kyc TEXT,
        doc_reservation_agreement TEXT,
        doc_spa TEXT,
        doc_others TEXT,
        comments TEXT,

        requested_by_signature TEXT,
        requested_by_date TEXT
    );
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS approvals (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        request_id INTEGER,
        level INTEGER,              -- 1 أو 2
        approver_name TEXT,
        decision TEXT,              -- Approved / Rejected
        comments TEXT,
        decided_at TEXT,
        FOREIGN KEY(request_id) REFERENCES requests(id)
    );
    """)

    db.commit()


# ============================================
# أدوات مساعدة
# ============================================

def is_manager_logged(level: int) -> bool:
    # نعتبر المدير داخل لو:
    # 1) داخل من /manager/<level> وعملنا له session[f"mgr{level}"] = True
    # 2) أو داخل من /manager/login/<level> وعملنا له session["manager_level"] = level
    return session.get(f"mgr{level}") is True or session.get("manager_level") == level



def require_manager(level: int):
    """ترجع Redirect لو المدير مش مسجل دخول، أو None لو تمام"""
    if not is_manager_logged(level):
        return redirect(url_for("manager_login", level=level))
    return None


def form_to_namespace(form, checkboxes=None):
    """يحّول بيانات الفورم إلى Object يشتغل مع existing.xxx"""
    data = {k: form.get(k, "") for k in form.keys()}
    if checkboxes:
        for cb in checkboxes:
            data[cb] = 1 if form.get(cb) == "on" else 0
    return SimpleNamespace(**data)


def validate_required(data):
    """
    data: dict من بيانات الفورم بعد المعالجة
    يرجّع list أخطاء (strings)
    """
    errors = []

    # 1) قسم Approval Request (كلّو إجباري)
    header_required = [
        ("project_name", "Project Name"),
        ("unit_number", "Unit Number"),
        ("paid_amount", "Paid Amount"),
        ("buyer_name", "Buyer Name"),
        ("agent_name", "Agent Name"),
        ("agency_name", "Agency Name"),
        ("agent_contact", "Agent Contact Number"),
    ]
    for field, label in header_required:
        if not data.get(field, "").strip():
            errors.append(f"{label} is required.")

    # 2) Requested By (إجباري)
    if not data.get("requested_by_signature", "").strip():
        errors.append("Agent Signature (Requested By) is required.")
    if not data.get("requested_by_date", "").strip():
        errors.append("Requested By Date is required.")

    # 3) لكل نوع تم اختياره: كل الحقول داخله إجباري
    types_required = {
        "price_reduction_selected": [
            "pr_listed_price",
            "pr_discount_amount",
            "pr_selling_price",
            "pr_discount_percent",
        ],
        "bulk_discount_selected": [
            "bd_listed_price",
            "bd_discount_amount",
            "bd_selling_price",
            "bd_discount_percent",
            "bd_units",
        ],
        "change_payment_plan_selected": [
            "cpp_down_payment_percent",
            "cpp_down_payment_date",
            "cpp_2nd_payment_percent",
            "cpp_2nd_payment_date",
            "cpp_3rd_payment_percent",
            "cpp_3rd_payment_date",
            "cpp_4th_payment_percent",
            "cpp_4th_payment_date",
            "cpp_5th_payment_percent",
            "cpp_5th_payment_date",
            "cpp_6th_payment_percent",
            "cpp_6th_payment_date",
            "cpp_completion_percent",
            "cpp_completion_date",
        ],
        "unit_switch_selected": [
            "us_booked_unit",
            "us_new_unit",
            "us_new_unit_selling_price",
        ],
        "unit_cancellation_selected": [
            "uc_amount_paid",
        ],
        "refund_selected": [
            "rf_booking_fees_amount",
            "rf_payment_amount",
            "rf_refund_amount",
        ],
        "late_payment_selected": [
            "lp_payment_schedule_no",
            "lp_initial_due_date",
            "lp_new_payment_date",
            "lp_penalty_amount",
            "lp_overdue_period",
        ],
        "waiver_late_fee_selected": [
            "wl_penalty_amount",
            "wl_waiver_amount",
        ],
        "issuance_spa_selected": [
            "spa_down_payment_received",
            "spa_percent",
        ],
        "registration_dld_selected": [
            "dld_down_payment_received",
            "dld_percent",
        ],
        "others_selected": [
            "others_text",
        ],
    }

    for flag, field_list in types_required.items():
        if data.get(flag):
            for f in field_list:
                if not data.get(f, "").strip():
                    errors.append(f"Field '{f}' is required because this request type is selected.")

    return errors


def build_data_from_form(form, *, for_update=False, prev_row=None):
    """يقرأ بيانات الفورم ويجهز dict لجدول requests"""
    now = datetime.utcnow().isoformat()
    cb_names = [
        "price_reduction_selected",
        "bulk_discount_selected",
        "change_payment_plan_selected",
        "unit_switch_selected",
        "unit_cancellation_selected",
        "refund_selected",
        "late_payment_selected",
        "waiver_late_fee_selected",
        "issuance_spa_selected",
        "registration_dld_selected",
        "others_selected",
    ]

    def cb(name):
        return 1 if form.get(name) == "on" else 0

    base = {
        "project_name": form.get("project_name", "").strip(),
        "unit_number": form.get("unit_number", "").strip(),
        "paid_amount": form.get("paid_amount", "").strip(),
        "buyer_name": form.get("buyer_name", "").strip(),
        "agent_name": form.get("agent_name", "").strip(),
        "agency_name": form.get("agency_name", "").strip(),
        "agent_contact": form.get("agent_contact", "").strip(),

        "price_reduction_selected": cb("price_reduction_selected"),
        "bulk_discount_selected": cb("bulk_discount_selected"),
        "change_payment_plan_selected": cb("change_payment_plan_selected"),
        "unit_switch_selected": cb("unit_switch_selected"),
        "unit_cancellation_selected": cb("unit_cancellation_selected"),
        "refund_selected": cb("refund_selected"),
        "late_payment_selected": cb("late_payment_selected"),
        "waiver_late_fee_selected": cb("waiver_late_fee_selected"),
        "issuance_spa_selected": cb("issuance_spa_selected"),
        "registration_dld_selected": cb("registration_dld_selected"),
        "others_selected": cb("others_selected"),

        "pr_listed_price": form.get("pr_listed_price", ""),
        "pr_discount_amount": form.get("pr_discount_amount", ""),
        "pr_selling_price": form.get("pr_selling_price", ""),
        "pr_discount_percent": form.get("pr_discount_percent", ""),

        "bd_listed_price": form.get("bd_listed_price", ""),
        "bd_discount_amount": form.get("bd_discount_amount", ""),
        "bd_selling_price": form.get("bd_selling_price", ""),
        "bd_discount_percent": form.get("bd_discount_percent", ""),
        "bd_units": form.get("bd_units", ""),

        "cpp_down_payment_percent": form.get("cpp_down_payment_percent", ""),
        "cpp_down_payment_date": form.get("cpp_down_payment_date", ""),
        "cpp_2nd_payment_percent": form.get("cpp_2nd_payment_percent", ""),
        "cpp_2nd_payment_date": form.get("cpp_2nd_payment_date", ""),
        "cpp_3rd_payment_percent": form.get("cpp_3rd_payment_percent", ""),
        "cpp_3rd_payment_date": form.get("cpp_3rd_payment_date", ""),
        "cpp_4th_payment_percent": form.get("cpp_4th_payment_percent", ""),
        "cpp_4th_payment_date": form.get("cpp_4th_payment_date", ""),
        "cpp_5th_payment_percent": form.get("cpp_5th_payment_percent", ""),
        "cpp_5th_payment_date": form.get("cpp_5th_payment_date", ""),
        "cpp_6th_payment_percent": form.get("cpp_6th_payment_percent", ""),
        "cpp_6th_payment_date": form.get("cpp_6th_payment_date", ""),
        "cpp_completion_percent": form.get("cpp_completion_percent", ""),
        "cpp_completion_date": form.get("cpp_completion_date", ""),

        "us_booked_unit": form.get("us_booked_unit", ""),
        "us_new_unit": form.get("us_new_unit", ""),
        "us_new_unit_selling_price": form.get("us_new_unit_selling_price", ""),

        "uc_amount_paid": form.get("uc_amount_paid", ""),

        "rf_booking_fees_amount": form.get("rf_booking_fees_amount", ""),
        "rf_payment_amount": form.get("rf_payment_amount", ""),
        "rf_refund_amount": form.get("rf_refund_amount", ""),

        "lp_payment_schedule_no": form.get("lp_payment_schedule_no", ""),
        "lp_initial_due_date": form.get("lp_initial_due_date", ""),
        "lp_new_payment_date": form.get("lp_new_payment_date", ""),
        "lp_penalty_amount": form.get("lp_penalty_amount", ""),
        "lp_overdue_period": form.get("lp_overdue_period", ""),

        "wl_downpayment_spa_date": form.get("wl_downpayment_spa_date", ""),
        "wl_2nd_payment_spa_date": form.get("wl_2nd_payment_spa_date", ""),
        "wl_3rd_payment_spa_date": form.get("wl_3rd_payment_spa_date", ""),
        "wl_4th_payment_spa_date": form.get("wl_4th_payment_spa_date", ""),
        "wl_5th_payment_spa_date": form.get("wl_5th_payment_spa_date", ""),
        "wl_6th_payment_spa_date": form.get("wl_6th_payment_spa_date", ""),

        "wl_penalty_amount": form.get("wl_penalty_amount", ""),
        "wl_waiver_amount": form.get("wl_waiver_amount", ""),

        "spa_down_payment_received": form.get("spa_down_payment_received", ""),
        "spa_percent": form.get("spa_percent", ""),

        "dld_down_payment_received": form.get("dld_down_payment_received", ""),
        "dld_percent": form.get("dld_percent", ""),

        "others_text": form.get("others_text", ""),

        "doc_kyc": form.get("doc_kyc", ""),
        "doc_reservation_agreement": form.get("doc_reservation_agreement", ""),
        "doc_spa": form.get("doc_spa", ""),
        "doc_others": form.get("doc_others", ""),
        "comments": form.get("comments", ""),

        "requested_by_signature": form.get("requested_by_signature", ""),
        "requested_by_date": form.get("requested_by_date", ""),
    }

    if not for_update:
        base["created_at"] = now
        base["status"] = "Pending L1"
        base["current_step"] = 1
        base["edit_token"] = secrets.token_urlsafe(24)

    base["updated_at"] = now
    return base


# ============================================
# الراوتات
# ============================================

@app.route("/")
def index():
    return redirect(url_for("new_request"))


# ---------- إنشاء طلب جديد ----------
@app.route("/request/new", methods=["GET", "POST"])
def new_request():
    db = get_db()
    errors = []
    existing = None

    if request.method == "POST":
        data = build_data_from_form(request.form, for_update=False)
        errors = validate_required(data)

        if errors:
            existing = SimpleNamespace(**data)
        else:
            columns = ", ".join(data.keys())
            placeholders = ", ".join(["?"] * len(data))
            cur = db.cursor()
            cur.execute(
                f"INSERT INTO requests ({columns}) VALUES ({placeholders})",
                list(data.values())
            )
            db.commit()
            req_id = cur.lastrowid

            # Redirect لمنع إعادة الإرسال عند الـ Refresh
            return redirect(url_for("view_request", req_id=req_id, submitted=1))

    return render_template(
        "request_form.html",
        existing=existing,
        errors=errors,
        project_choices=PROJECT_CHOICES,
        unit_choices=UNIT_CHOICES
    )


# ---------- تعديل طلب لصاحب الطلب ----------
@app.route("/request/edit/<token>", methods=["GET", "POST"])
def edit_request(token):
    db = get_db()
    cur = db.cursor()
    cur.execute("SELECT * FROM requests WHERE edit_token = ?", (token,))
    row = cur.fetchone()
    if not row:
        abort(404)

    errors = []
    existing = row

    if request.method == "POST":
        data = build_data_from_form(request.form, for_update=True, prev_row=row)
        errors = validate_required(data)

        if not errors:
            set_clause = ", ".join([f"{k}=?" for k in data.keys()])
            cur.execute(
                f"UPDATE requests SET {set_clause} WHERE id = ?",
                list(data.values()) + [row["id"]]
            )
            db.commit()
            return redirect(url_for("view_request", req_id=row["id"]))

        existing = SimpleNamespace(**data)

    return render_template(
        "request_form.html",
        existing=existing,
        edit_token=token,
        errors=errors,
        project_choices=PROJECT_CHOICES,
        unit_choices=UNIT_CHOICES
    )


# ---------- عرض طلب (قراءة فقط) ----------
@app.route("/request/<int:req_id>")
def view_request(req_id):
    db = get_db()
    cur = db.cursor()
    cur.execute("SELECT * FROM requests WHERE id = ?", (req_id,))
    row = cur.fetchone()
    if not row:
        abort(404)

    cur.execute("SELECT * FROM approvals WHERE request_id = ? ORDER BY level, decided_at", (req_id,))
    approvals = cur.fetchall()

    submitted = request.args.get("submitted") == "1"
    edit_link = None
    if submitted:
        edit_link = url_for("edit_request", token=row["edit_token"], _external=True)

    # signatures for managers (من جدول approvals)
    manager1_sig = None
    manager2_sig = None
    for a in approvals:
        if a["level"] == 1:
            manager1_sig = a
        elif a["level"] == 2:
            manager2_sig = a

    return render_template(
        "request_view.html",
        req=row,
        req_id=req_id,
        approvals=approvals,
        edit_link=edit_link,
        from_submit=submitted,
        manager_level=None,
        error=None,
        manager1_sig=manager1_sig,
        manager2_sig=manager2_sig
    )


# ---------- لوجين المدير ----------
@app.route("/manager/login/<int:level>", methods=["GET", "POST"])
def manager_login(level):
    if level not in (1, 2):
        abort(404)

    error = None
    if request.method == "POST":
        pwd = request.form.get("password", "")
        if (level == 1 and pwd == MANAGER1_PASSWORD) or (level == 2 and pwd == MANAGER2_PASSWORD):
            session["manager_level"] = level
            return redirect(url_for("manager_dashboard", level=level))
        else:
            error = "Wrong password"

    return render_template(
        "manager_dashboard.html",
        login_only=True,
        level=level,
        error=error,
        show_create=False

    )


# ---------- داشبورد المدير ----------
@app.route("/manager/<int:level>", methods=["GET", "POST"])
def manager_dashboard(level):
    # --------- LOGIN ---------
    if session.get(f"mgr{level}") != True:
        # محاولة تسجيل دخول
        if request.method == "POST":
            pwd = request.form.get("password", "")
            if pwd == MANAGER_PASSWORDS.get(level):
                session[f"mgr{level}"] = True
                return redirect(url_for("manager_dashboard", level=level))
            else:
                return render_template(
                    "manager_dashboard.html",
                    login_only=True,
                    level=level,
                    error="Wrong password",
                )

        # أول مرة يفتح الصفحة -> فورم لوجن
        return render_template(
            "manager_dashboard.html",
            login_only=True,
            level=level
        )

       # --------- LOGGED IN ---------
    flt = request.args.get("filter", "all")
    sort = request.args.get("sort", "latest")

    # فلاتر جديدة لاختيار Project و Unit
    flt_project = request.args.get("project", "")
    flt_unit = request.args.get("unit", "")

    conn = sqlite3.connect("approval_requests.db")
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # ---------- إحصائيات ----------
    def scalar(q, params=()):
        cur.execute(q, params)
        return cur.fetchone()[0]

    total       = scalar("SELECT COUNT(*) FROM requests")
    pending_l1  = scalar("SELECT COUNT(*) FROM requests WHERE status='Pending L1'")
    pending_l2  = scalar("SELECT COUNT(*) FROM requests WHERE status='Pending L2'")
    approved    = scalar("SELECT COUNT(*) FROM requests WHERE status='Approved'")
    rejected    = scalar("SELECT COUNT(*) FROM requests WHERE status='Rejected'")

    # ----------- بناء SQL ديناميكي -------------
    where = []
    params = []

    # فلتر حالة الطلب
    if flt == "pending_l1":
        where.append("status='Pending L1'")
    elif flt == "pending_l2":
        where.append("status='Pending L2'")
    elif flt == "approved":
        where.append("status='Approved'")
    elif flt == "rejected":
        where.append("status='Rejected'")

    # فلتر Project
    if flt_project:
        where.append("project_name = ?")
        params.append(flt_project)

    # فلتر Unit
    if flt_unit:
        where.append("unit_number = ?")
        params.append(flt_unit)

    # بناء جملة SELECT
    sql = "SELECT * FROM requests"
    if where:
        sql += " WHERE " + " AND ".join(where)

    # ---------- فرز ----------
    if sort == "project":
        sql += " ORDER BY project_name ASC"
    elif sort == "unit":
        sql += " ORDER BY unit_number ASC"
    else:  # latest
        sql += " ORDER BY id DESC"

    cur.execute(sql, params)
    all_requests = cur.fetchall()

    # استخراج قائمة project / unit موجودة فعلياً في قاعدة البيانات
    cur.execute("SELECT DISTINCT project_name FROM requests ORDER BY project_name")
    project_list = [r[0] for r in cur.fetchall()]

    cur.execute("SELECT DISTINCT unit_number FROM requests ORDER BY unit_number")
    unit_list = [r[0] for r in cur.fetchall()]

    conn.close()

    return render_template(
        "manager_dashboard.html",
        login_only=False,
        level=level,
        total=total,
        pending_l1=pending_l1,
        pending_l2=pending_l2,
        approved=approved,
        rejected=rejected,
        all_requests=all_requests,
        active_filter=flt,
        active_sort=sort,
        projects=project_list,
        units=unit_list,
        active_project=flt_project,
        active_unit=flt_unit
    )


# -------- Viewer Dashboard ----------
@app.route("/viewer")
def viewer_dashboard():
    if not session.get("viewer"):
        return redirect(url_for("viewer_login"))

    conn = sqlite3.connect("approval_requests.db")
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # نفس إحصائيات المدير
    stats = {
        "total": cur.execute("SELECT COUNT(*) FROM requests").fetchone()[0],
        "pending_l1": cur.execute("SELECT COUNT(*) FROM requests WHERE status='Pending L1'").fetchone()[0],
        "pending_l2": cur.execute("SELECT COUNT(*) FROM requests WHERE status='Pending L2'").fetchone()[0],
        "approved": cur.execute("SELECT COUNT(*) FROM requests WHERE status='Approved'").fetchone()[0],
        "rejected": cur.execute("SELECT COUNT(*) FROM requests WHERE status='Rejected'").fetchone()[0],
    }

    # يجلب الكل مثل admin
    cur.execute("SELECT * FROM requests ORDER BY id DESC")
    all_requests = cur.fetchall()
    conn.close()

    return render_template(
        "viewer_dashboard.html",
        login_only=False,
        stats=stats,
        all_requests=all_requests
    )



# ---------- صفحة طلب للمدير + Approve/Reject ----------
@app.route("/manager/<int:level>/request/<int:req_id>", methods=["GET", "POST"])
def manager_request(level, req_id):
    if level not in (1, 2):
        abort(404)

    redir = require_manager(level)
    if redir:
        return redir

    db = get_db()
    cur = db.cursor()
    cur.execute("SELECT * FROM requests WHERE id = ?", (req_id,))
    row = cur.fetchone()
    if not row:
        abort(404)

    cur.execute("SELECT * FROM approvals WHERE request_id = ? ORDER BY level, decided_at", (req_id,))
    approvals = cur.fetchall()

    error = None

    if request.method == "POST":
        decision = request.form.get("decision")
        approver_name = request.form.get("approver_name", "").strip()
        comments = request.form.get("comments", "").strip()

        if decision not in ("Approved", "Rejected"):
            error = "Invalid decision"
        elif not approver_name:
            error = "Approver name required"
        else:
            now = datetime.utcnow().isoformat()

            # لا تسمح لـ Manager 2 يوافق لو لسا Pending L1
            if level == 2 and row["status"] != "Pending L2":
                error = "Request is not ready for Level 2."
            else:
                cur.execute("""
                    INSERT INTO approvals (request_id, level, approver_name, decision, comments, decided_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (req_id, level, approver_name, decision, comments, now))

                # تحديث حالة الطلب
                new_status = row["status"]
                new_step = row["current_step"]

                if level == 1:
                    if decision == "Approved":
                        new_status = "Pending L2"
                        new_step = 2
                    else:
                        new_status = "Rejected"
                        new_step = 0
                elif level == 2:
                    if decision == "Approved":
                        new_status = "Approved"
                        new_step = 0
                    else:
                        new_status = "Rejected"
                        new_step = 0

                cur.execute(
                    "UPDATE requests SET status=?, current_step=?, updated_at=? WHERE id=?",
                    (new_status, new_step, now, req_id)
                )
                db.commit()
                return redirect(url_for("manager_dashboard", level=level))

    # إعادة جلب بعد أي عملية
    cur.execute("SELECT * FROM requests WHERE id = ?", (req_id,))
    row = cur.fetchone()
    cur.execute("SELECT * FROM approvals WHERE request_id = ? ORDER BY level, decided_at", (req_id,))
    approvals = cur.fetchall()

    manager1_sig = None
    manager2_sig = None
    for a in approvals:
        if a["level"] == 1:
            manager1_sig = a
        elif a["level"] == 2:
            manager2_sig = a

    return render_template(
        "request_view.html",
        req=row,
        req_id=req_id,
        approvals=approvals,
        manager_level=level,
        error=error,
        edit_link=None,
        from_submit=False,
        manager1_sig=manager1_sig,
        manager2_sig=manager2_sig
    )


# -------- Viewer Login ----------
@app.route("/viewer/login", methods=["GET", "POST"])
def viewer_login():
    error = None
    if request.method == "POST":
        u = request.form.get("username", "")
        p = request.form.get("password", "")
        if u == VIEWER_USERNAME and p == VIEWER_PASSWORD:
            session["viewer"] = True
            return redirect(url_for("viewer_dashboard"))
        else:
            error = "Wrong username or password"

    return render_template("viewer_dashboard.html", login_only=True, error=error)


# ============================================
# تشغيل التطبيق
# ============================================

if __name__ == "__main__":
    with app.app_context():
        init_db()
    app.run(host="0.0.0.0", port=5000, debug=False)
