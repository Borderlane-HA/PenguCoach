from __future__ import annotations
from datetime import date, datetime, timedelta
import calendar
import json
from pathlib import Path
from typing import Optional, Literal, Any

from fastapi import FastAPI, Depends, HTTPException, Response, Query, BackgroundTasks
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy import select, func, inspect, text
from sqlalchemy.orm import Session

from .db import Base, engine, get_db, SessionLocal
from .models import (
    User, Expense, ExpensePrice, Account, Category, Setting, ReminderAction,
    HiddenCatalogItem, AIProfile, AIConversation, AIMessage, AIBrain,
)
from .security import hash_password, verify_password, make_session, session_user_id, encrypt_secret, decrypt_secret
from .ai import analyze_costs, chat_finances

APP_VERSION = '0.3.0'
app = FastAPI(title='PenguCost', version=APP_VERSION)
Base.metadata.create_all(engine)


def migrate_schema():
    # create_all does not add columns to existing SQLite tables. Keep upgrades in-place.
    columns = {c['name'] for c in inspect(engine).get_columns('expenses')}
    statements = []
    if 'entry_type' not in columns:
        statements.append("ALTER TABLE expenses ADD COLUMN entry_type VARCHAR(16) DEFAULT 'expense'")
    if 'minimum_term_months' not in columns:
        statements.append('ALTER TABLE expenses ADD COLUMN minimum_term_months INTEGER')
    if 'renewal_period_months' not in columns:
        statements.append('ALTER TABLE expenses ADD COLUMN renewal_period_months INTEGER')
    if 'cancelled_on' not in columns:
        statements.append('ALTER TABLE expenses ADD COLUMN cancelled_on DATE')
    if statements:
        with engine.begin() as conn:
            for statement in statements:
                conn.execute(text(statement))
    category_columns = {c['name'] for c in inspect(engine).get_columns('categories')}
    if 'color' not in category_columns:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE categories ADD COLUMN color VARCHAR(16) DEFAULT '#5B5CF0'"))
    with engine.begin() as conn:
        conn.execute(text('CREATE INDEX IF NOT EXISTS ix_expenses_created_by ON expenses (created_by)'))
        conn.execute(text('CREATE INDEX IF NOT EXISTS ix_expenses_entry_type ON expenses (entry_type)'))


migrate_schema()

DEFAULT_CATEGORIES = [
    ('Abos', 'sparkles', '#7C6CF2'), ('Versicherungen', 'shield', '#4A78D0'), ('Energie', 'zap', '#E3A124'),
    ('Wohnen', 'house', '#CE6B4D'), ('Mobilität', 'car', '#2E9B84'), ('Telekommunikation', 'wifi', '#4B91C8'),
    ('Finanzen', 'landmark', '#8C67B8'), ('Gesundheit', 'heart', '#D45B78'), ('Sonstiges', 'wallet', '#7B8798')
]

AI_PROVIDERS = [
    {'id': 'ollama', 'label': 'Ollama', 'default_base_url': 'http://127.0.0.1:11434/v1', 'key_optional': True},
    {'id': 'openai', 'label': 'OpenAI', 'default_base_url': 'https://api.openai.com/v1', 'key_optional': False},
    {'id': 'grok', 'label': 'Grok / xAI', 'default_base_url': 'https://api.x.ai/v1', 'key_optional': False},
    {'id': 'gemini', 'label': 'Google Gemini', 'default_base_url': 'https://generativelanguage.googleapis.com/v1beta/openai', 'key_optional': False},
    {'id': 'ionos', 'label': 'IONOS AI Model Hub', 'default_base_url': '', 'key_optional': False},
    {'id': 'claude', 'label': 'Claude / Anthropic', 'default_base_url': 'https://api.anthropic.com', 'key_optional': False},
    {'id': 'custom', 'label': 'OpenAI-kompatibel / Custom', 'default_base_url': '', 'key_optional': True},
]
PROVIDER_MAP = {x['id']: x for x in AI_PROVIDERS}


def seed(db: Session):
    if not db.scalar(select(func.count(Category.id))):
        db.add_all([Category(name=n, icon=i, color=c) for n, i, c in DEFAULT_CATEGORIES])
        db.commit()


class LoginIn(BaseModel):
    username: str
    password: str


class BootstrapIn(BaseModel):
    username: str = Field(min_length=3)
    display_name: str = 'Administrator'
    password: str = Field(min_length=8)


class UserIn(BaseModel):
    username: str
    display_name: str = ''
    password: str = Field(min_length=8)
    role: str = 'member'


class UserPatch(BaseModel):
    display_name: Optional[str] = None
    password: Optional[str] = None
    role: Optional[str] = None
    is_active: Optional[bool] = None


class AccountIn(BaseModel):
    name: str
    kind: str = 'bank'
    note: str = ''


class CategoryIn(BaseModel):
    name: str
    icon: str = 'wallet'
    color: str = '#5B5CF0'


class CategoryPatch(BaseModel):
    name: Optional[str] = None
    icon: Optional[str] = None
    color: Optional[str] = None


class ExpenseIn(BaseModel):
    name: str
    provider: str = ''
    entry_type: Literal['expense', 'income'] = 'expense'
    amount: float = Field(gt=0)
    currency: str = 'EUR'
    billing_interval: str = 'monthly'
    interval_months: int = 1
    category_id: Optional[int] = None
    account_id: Optional[int] = None
    start_date: Optional[date] = None
    next_due_date: Optional[date] = None
    contract_end: Optional[date] = None
    cancellation_date: Optional[date] = None
    minimum_term_months: Optional[int] = Field(default=None, ge=1)
    renewal_period_months: Optional[int] = Field(default=None, ge=1)
    cancellation_notice_days: Optional[int] = None
    auto_renew: bool = False
    status: str = 'active'
    essential: bool = False
    tags: str = ''
    notes: str = ''
    price_effective_from: Optional[date] = None


class AIProfileIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    provider: str = 'custom'
    base_url: str = ''
    model: str = Field(min_length=1, max_length=200)
    api_key: str = ''
    enabled: bool = True


class AIProfilePatch(BaseModel):
    name: Optional[str] = None
    provider: Optional[str] = None
    base_url: Optional[str] = None
    model: Optional[str] = None
    api_key: Optional[str] = None
    enabled: Optional[bool] = None


class ReminderSettingsIn(BaseModel):
    cancellation_reminder_days: int = Field(default=30, ge=0, le=3650)


class UserPreferencesIn(BaseModel):
    language: Optional[Literal['de', 'en']] = None
    ai_prompt: Optional[str] = Field(default=None, max_length=6000)
    theme: Optional[Literal['system', 'light', 'midnight', 'nordic', 'graphite', 'emerald']] = None


class ReminderActionIn(BaseModel):
    action: Literal['done', 'cancelled', 'snooze']
    event_key: str = Field(min_length=1, max_length=160)
    snooze_days: Optional[int] = Field(default=None, ge=1, le=365)


class AIAnalyzeIn(BaseModel):
    goal: str = 'Reduce monthly recurring costs'
    expense_ids: list[int] = []
    language: str = 'de'
    profile_id: Optional[int] = None


class AIConversationIn(BaseModel):
    profile_id: Optional[int] = None
    mode: Literal['analysis', 'savings', 'chat'] = 'analysis'
    target_savings: Optional[float] = Field(default=None, ge=0, le=1000000)
    expense_ids: list[int] = []
    title: Optional[str] = Field(default=None, max_length=180)


class AIChatIn(BaseModel):
    message: str = Field(min_length=1, max_length=12000)
    profile_id: Optional[int] = None
    expense_ids: list[int] = []
    mode: Optional[Literal['analysis', 'savings', 'chat']] = None
    target_savings: Optional[float] = Field(default=None, ge=0, le=1000000)
    language: Literal['de', 'en'] = 'de'


class AIBrainIn(BaseModel):
    summary: str = Field(default='', max_length=12000)


def current_user(uid: int = Depends(session_user_id), db: Session = Depends(get_db)):
    user = db.get(User, uid)
    if not user or not user.is_active:
        raise HTTPException(401, 'Not authenticated')
    return user


def require_admin(user: User = Depends(current_user)):
    if user.role != 'admin':
        raise HTTPException(403, 'Admin only')
    return user


def add_months(value: date, months: int) -> date:
    idx = value.month - 1 + months
    year = value.year + idx // 12
    month = idx % 12 + 1
    day = min(value.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def price_at(x: Expense, when: date) -> float:
    prices = sorted(x.prices, key=lambda p: p.valid_from)
    applicable = [p for p in prices if p.valid_from <= when]
    if applicable:
        return applicable[-1].amount
    if prices:
        return prices[0].amount
    return x.amount


def effective_contract_end(x: Expense, today: date) -> date | None:
    end = x.contract_end
    if not end or not x.auto_renew or not x.renewal_period_months:
        return end
    guard = 0
    while end < today and guard < 600:
        end = add_months(end, x.renewal_period_months)
        guard += 1
    return end


def is_effectively_active(x: Expense, when: date | None = None) -> bool:
    when = when or date.today()
    # A cancelled contract still creates cash flow until its effective end.
    # Only paused/ended entries are excluded from current reporting.
    if x.status in {'paused', 'ended'}:
        return False
    end = effective_contract_end(x, when)
    return not end or end >= when


def expense_dict(x: Expense, as_of: date | None = None):
    today = as_of or date.today()
    current_amount = price_at(x, today)
    months = x.interval_months or {'monthly': 1, 'quarterly': 3, 'halfyearly': 6, 'yearly': 12}.get(x.billing_interval, 1)
    monthly = round(current_amount / months, 2)
    yearly = round(monthly * 12, 2)
    prices = sorted(x.prices, key=lambda p: p.valid_from)
    price_history = []
    for i, p in enumerate(prices):
        valid_to = (prices[i + 1].valid_from - timedelta(days=1)) if i + 1 < len(prices) else None
        price_history.append({'id': p.id, 'amount': p.amount, 'valid_from': p.valid_from, 'valid_to': valid_to})
    upcoming_price = next((p for p in prices if p.valid_from > today), None)
    next_end = effective_contract_end(x, today)
    next_cancel = x.cancellation_date
    if next_end and x.cancellation_notice_days is not None and (not next_cancel or next_cancel < today or next_end != x.contract_end):
        next_cancel = next_end - timedelta(days=max(0, x.cancellation_notice_days))
    return {
        'id': x.id, 'name': x.name, 'provider': x.provider, 'entry_type': (x.entry_type or 'expense'), 'amount': current_amount, 'currency': x.currency,
        'billing_interval': x.billing_interval, 'interval_months': months, 'monthly_equivalent': monthly,
        'yearly_equivalent': yearly, 'category_id': x.category_id, 'category': x.category.name if x.category else None,
        'category_color': x.category.color if x.category else '#7B8798', 'account_id': x.account_id,
        'account': x.account.name if x.account else None, 'start_date': x.start_date, 'next_due_date': x.next_due_date,
        'contract_end': x.contract_end, 'effective_contract_end': next_end, 'cancellation_date': x.cancellation_date,
        'effective_cancellation_date': next_cancel, 'minimum_term_months': x.minimum_term_months,
        'renewal_period_months': x.renewal_period_months, 'cancellation_notice_days': x.cancellation_notice_days,
        'cancelled_on': x.cancelled_on, 'auto_renew': x.auto_renew, 'status': x.status, 'essential': x.essential,
        'tags': x.tags, 'notes': x.notes, 'price_history': price_history,
        'next_price_change': ({'amount': upcoming_price.amount, 'valid_from': upcoming_price.valid_from} if upcoming_price else None),
    }


def setting_value(db: Session, key: str, default: str = '') -> str:
    row = db.get(Setting, key)
    return row.value if row else default


def set_setting_value(db: Session, key: str, value: str):
    row = db.get(Setting, key)
    if row:
        row.value = value
    else:
        db.add(Setting(key=key, value=value))


DEFAULT_AI_PROMPT_DE = 'Ich möchte meine monatlichen Fixkosten sinnvoll reduzieren, ohne wichtige Leistungen zu verlieren.'
DEFAULT_AI_PROMPT_EN = 'I want to reduce my monthly fixed costs sensibly without losing important services.'

def reminder_days_for(db: Session, user: User) -> int:
    return int(setting_value(db, f'reminders.cancellation_days.user.{user.id}', setting_value(db, 'reminders.cancellation_days', '30')))

def language_for(db: Session, user: User) -> str:
    value = setting_value(db, f'preferences.language.user.{user.id}', 'de')
    return value if value in {'de', 'en'} else 'de'

def ai_prompt_for(db: Session, user: User) -> str:
    fallback = DEFAULT_AI_PROMPT_EN if language_for(db, user) == 'en' else DEFAULT_AI_PROMPT_DE
    return setting_value(db, f'preferences.ai_prompt.user.{user.id}', fallback) or fallback

def theme_for(db: Session, user: User) -> str:
    value = setting_value(db, f'preferences.theme.user.{user.id}', 'system')
    return value if value in {'system', 'light', 'midnight', 'nordic', 'graphite', 'emerald'} else 'system'


def adopt_orphan_expenses(db: Session, admin_id: int):
    db.execute(text('UPDATE expenses SET created_by = :uid WHERE created_by IS NULL'), {'uid': admin_id})


def hidden_ids(db: Session, user: User, item_type: str) -> set[int]:
    if user.role == 'admin':
        return set()
    return set(db.scalars(select(HiddenCatalogItem.item_id).where(
        HiddenCatalogItem.user_id == user.id,
        HiddenCatalogItem.item_type == item_type,
    )))


def hide_catalog_item(db: Session, user: User, item_type: str, item_id: int):
    existing = db.scalar(select(HiddenCatalogItem).where(
        HiddenCatalogItem.user_id == user.id,
        HiddenCatalogItem.item_type == item_type,
        HiddenCatalogItem.item_id == item_id,
    ))
    if not existing:
        db.add(HiddenCatalogItem(user_id=user.id, item_type=item_type, item_id=item_id))


def owned_expense(db: Session, user: User, expense_id: int) -> Expense:
    x = db.scalar(select(Expense).where(Expense.id == expense_id, Expense.created_by == user.id))
    if not x:
        raise HTTPException(404, 'Not found')
    return x


def provider_defaults(provider: str) -> dict:
    if provider not in PROVIDER_MAP:
        raise HTTPException(400, 'Unknown AI provider')
    return PROVIDER_MAP[provider]


def ai_profile_dict(x: AIProfile, admin: bool = False):
    provider = PROVIDER_MAP.get(x.provider, PROVIDER_MAP['custom'])
    row = {
        'id': x.id, 'name': x.name, 'provider': x.provider, 'provider_label': provider['label'],
        'model': x.model, 'enabled': x.enabled,
    }
    if admin:
        row.update({'base_url': x.base_url, 'has_api_key': bool(x.api_key)})
    return row


@app.on_event('startup')
def startup():
    db = next(get_db())
    seed(db)
    changed = False
    for item in db.scalars(select(Expense)):
        if not item.prices:
            db.add(ExpensePrice(expense_id=item.id, amount=item.amount, valid_from=item.start_date or (item.created_at.date() if item.created_at else date.today())))
            changed = True
    if changed:
        db.commit()

    if not db.get(Setting, 'migration.category_colors_012'):
        palette = {name: color for name, _icon, color in DEFAULT_CATEGORIES}
        for category in db.scalars(select(Category)):
            if category.name in palette and (not category.color or category.color.upper() == '#5B5CF0'):
                category.color = palette[category.name]
        db.add(Setting(key='migration.category_colors_012', value='done'))
        db.commit()

    admin = db.scalar(select(User).where(User.role == 'admin').order_by(User.id))
    if admin:
        adopt_orphan_expenses(db, admin.id)
        db.execute(text('UPDATE reminder_actions SET created_by = (SELECT created_by FROM expenses WHERE expenses.id = reminder_actions.expense_id) WHERE created_by IS NULL'))
        db.commit()

    # Import the former single OpenAI-compatible configuration once into an admin-managed profile.
    if not db.scalar(select(func.count(AIProfile.id))):
        old_base = setting_value(db, 'ai.base_url')
        old_model = setting_value(db, 'ai.model')
        old_key = setting_value(db, 'ai.api_key')
        old_enabled = setting_value(db, 'ai.enabled', 'false') == 'true'
        if old_base or old_model or old_key:
            old_provider = 'ollama' if ':11434' in old_base else 'custom'
            if old_provider == 'ollama' and old_base and not old_base.rstrip('/').endswith('/v1'):
                old_base = old_base.rstrip('/') + '/v1'
            db.add(AIProfile(name='Standard', provider=old_provider, base_url=old_base, model=old_model or 'model', api_key=old_key, enabled=old_enabled))
            db.commit()
    db.close()


@app.get('/api/health')
def health():
    return {'status': 'ok', 'service': 'PenguCost', 'version': APP_VERSION}


@app.get('/api/auth/status')
def auth_status(db: Session = Depends(get_db)):
    return {'needs_bootstrap': (db.scalar(select(func.count(User.id))) or 0) == 0}


@app.post('/api/auth/bootstrap')
def bootstrap(data: BootstrapIn, response: Response, db: Session = Depends(get_db)):
    if (db.scalar(select(func.count(User.id))) or 0) > 0:
        raise HTTPException(409, 'Already initialized')
    user = User(username=data.username.strip().lower(), display_name=data.display_name, password_hash=hash_password(data.password), role='admin')
    db.add(user)
    db.flush()
    adopt_orphan_expenses(db, user.id)
    db.commit()
    db.refresh(user)
    response.set_cookie('pengucost_session', make_session(user.id), httponly=True, samesite='lax', secure=False, max_age=2592000)
    return {'id': user.id, 'username': user.username, 'display_name': user.display_name, 'role': user.role}


@app.post('/api/auth/login')
def login(data: LoginIn, response: Response, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.username == data.username.strip().lower()))
    if not user or not user.is_active or not verify_password(data.password, user.password_hash):
        raise HTTPException(401, 'Invalid credentials')
    response.set_cookie('pengucost_session', make_session(user.id), httponly=True, samesite='lax', secure=False, max_age=2592000)
    return {'id': user.id, 'username': user.username, 'display_name': user.display_name, 'role': user.role}


@app.post('/api/auth/logout')
def logout(response: Response):
    response.delete_cookie('pengucost_session')
    return {'ok': True}


@app.get('/api/me')
def me(user: User = Depends(current_user)):
    return {'id': user.id, 'username': user.username, 'display_name': user.display_name, 'role': user.role, 'version': APP_VERSION}


@app.get('/api/users')
def users(_: User = Depends(require_admin), db: Session = Depends(get_db)):
    # Deliberately only account metadata. Admin endpoints never expose another user's cost data.
    return [{'id': u.id, 'username': u.username, 'display_name': u.display_name, 'role': u.role, 'is_active': u.is_active} for u in db.scalars(select(User).order_by(User.username))]


@app.post('/api/users')
def create_user(data: UserIn, _: User = Depends(require_admin), db: Session = Depends(get_db)):
    u = User(username=data.username.lower().strip(), display_name=data.display_name, password_hash=hash_password(data.password), role=data.role)
    db.add(u)
    try:
        db.commit()
        db.refresh(u)
    except Exception:
        db.rollback()
        raise HTTPException(409, 'Username already exists')
    return {'id': u.id}


@app.patch('/api/users/{user_id}')
def patch_user(user_id: int, data: UserPatch, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    u = db.get(User, user_id)
    if not u:
        raise HTTPException(404, 'User not found')
    if data.display_name is not None:
        u.display_name = data.display_name
    if data.password:
        u.password_hash = hash_password(data.password)
    if data.role is not None:
        u.role = data.role
    if data.is_active is not None:
        if u.id == admin.id and not data.is_active:
            raise HTTPException(400, 'Cannot disable current admin')
        u.is_active = data.is_active
    db.commit()
    return {'ok': True}


@app.get('/api/accounts')
def get_accounts(user: User = Depends(current_user), db: Session = Depends(get_db)):
    hidden = hidden_ids(db, user, 'account')
    return [{'id': x.id, 'name': x.name, 'kind': x.kind, 'note': x.note} for x in db.scalars(select(Account).order_by(Account.name)) if x.id not in hidden]


@app.post('/api/accounts')
def add_account(data: AccountIn, _: User = Depends(require_admin), db: Session = Depends(get_db)):
    x = Account(**data.model_dump())
    db.add(x)
    try:
        db.commit()
        db.refresh(x)
    except Exception:
        db.rollback()
        raise HTTPException(409, 'Account already exists')
    return {'id': x.id}


@app.delete('/api/accounts/{item_id}')
def delete_account(item_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    x = db.get(Account, item_id)
    if not x:
        raise HTTPException(404, 'Not found')
    if user.role != 'admin':
        hide_catalog_item(db, user, 'account', item_id)
        db.commit()
        return {'ok': True, 'hidden_only': True}
    refs = db.scalar(select(func.count(Expense.id)).where(Expense.account_id == item_id)) or 0
    if refs:
        raise HTTPException(409, 'Konto wird noch verwendet und kann deshalb nicht global gelöscht werden')
    db.delete(x)
    db.commit()
    return {'ok': True, 'hidden_only': False}


@app.get('/api/categories')
def get_categories(user: User = Depends(current_user), db: Session = Depends(get_db)):
    hidden = hidden_ids(db, user, 'category')
    return [{'id': x.id, 'name': x.name, 'icon': x.icon, 'color': x.color or '#5B5CF0'} for x in db.scalars(select(Category).order_by(Category.name)) if x.id not in hidden]


@app.post('/api/categories')
def add_category(data: CategoryIn, _: User = Depends(require_admin), db: Session = Depends(get_db)):
    x = Category(**data.model_dump())
    db.add(x)
    try:
        db.commit()
        db.refresh(x)
    except Exception:
        db.rollback()
        raise HTTPException(409, 'Category already exists')
    return {'id': x.id, 'name': x.name, 'icon': x.icon, 'color': x.color or '#5B5CF0'}


@app.patch('/api/categories/{item_id}')
def patch_category(item_id: int, data: CategoryPatch, _: User = Depends(require_admin), db: Session = Depends(get_db)):
    x = db.get(Category, item_id)
    if not x:
        raise HTTPException(404, 'Not found')
    if data.name is not None:
        x.name = data.name.strip()
    if data.icon is not None:
        x.icon = data.icon
    if data.color is not None:
        color = data.color.strip()
        if not (len(color) == 7 and color.startswith('#') and all(c in '0123456789abcdefABCDEF' for c in color[1:])):
            raise HTTPException(400, 'Color must be a hex value like #5B5CF0')
        x.color = color.upper()
    db.commit()
    return {'ok': True}


@app.delete('/api/categories/{item_id}')
def delete_category(item_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    x = db.get(Category, item_id)
    if not x:
        raise HTTPException(404, 'Not found')
    if user.role != 'admin':
        hide_catalog_item(db, user, 'category', item_id)
        db.commit()
        return {'ok': True, 'hidden_only': True}
    refs = db.scalar(select(func.count(Expense.id)).where(Expense.category_id == item_id)) or 0
    if refs:
        raise HTTPException(409, 'Rubrik wird noch verwendet und kann deshalb nicht global gelöscht werden')
    db.delete(x)
    db.commit()
    return {'ok': True, 'hidden_only': False}


@app.post('/api/catalog/reset-hidden')
def reset_hidden_catalog(user: User = Depends(current_user), db: Session = Depends(get_db)):
    rows = list(db.scalars(select(HiddenCatalogItem).where(HiddenCatalogItem.user_id == user.id)))
    for row in rows:
        db.delete(row)
    db.commit()
    return {'ok': True, 'restored': len(rows)}


@app.get('/api/expenses')
def get_expenses(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return [expense_dict(x) for x in db.scalars(select(Expense).where(Expense.created_by == user.id).order_by(Expense.name))]


def normalized_expense_data(data: ExpenseIn):
    payload = data.model_dump(exclude={'price_effective_from'})
    if not payload.get('contract_end') and payload.get('start_date') and payload.get('minimum_term_months'):
        payload['contract_end'] = add_months(payload['start_date'], payload['minimum_term_months']) - timedelta(days=1)
    if not payload.get('cancellation_date') and payload.get('contract_end') and payload.get('cancellation_notice_days') is not None:
        payload['cancellation_date'] = payload['contract_end'] - timedelta(days=max(0, payload['cancellation_notice_days']))
    return payload


def upsert_price(db: Session, x: Expense, amount: float, effective_from: date):
    existing = next((p for p in x.prices if p.valid_from == effective_from), None)
    if existing:
        existing.amount = amount
    else:
        x.prices.append(ExpensePrice(expense_id=x.id, amount=amount, valid_from=effective_from))


@app.post('/api/expenses')
def add_expense(data: ExpenseIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    payload = normalized_expense_data(data)
    initial_amount = payload['amount']
    x = Expense(**payload, created_by=user.id)
    db.add(x)
    db.flush()
    db.add(ExpensePrice(expense_id=x.id, amount=initial_amount, valid_from=data.price_effective_from or data.start_date or date.today()))
    db.commit()
    db.refresh(x)
    return expense_dict(x)


@app.put('/api/expenses/{item_id}')
def update_expense(item_id: int, data: ExpenseIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    x = owned_expense(db, user, item_id)
    old_contract_end = x.contract_end
    old_cancellation_date = x.cancellation_date
    payload = normalized_expense_data(data)
    if (payload.get('contract_end') != old_contract_end and data.cancellation_date == old_cancellation_date
            and payload.get('contract_end') and payload.get('cancellation_notice_days') is not None):
        payload['cancellation_date'] = payload['contract_end'] - timedelta(days=max(0, payload['cancellation_notice_days']))
    requested_amount = payload.pop('amount')
    effective = data.price_effective_from or date.today()
    if round(price_at(x, effective), 2) != round(requested_amount, 2):
        upsert_price(db, x, requested_amount, effective)
    for k, v in payload.items():
        setattr(x, k, v)
    if x.auto_renew and x.cancelled_on is not None:
        x.cancelled_on = None
    x.amount = price_at(x, date.today())
    db.commit()
    db.refresh(x)
    return expense_dict(x)


@app.delete('/api/expenses/{item_id}')
def delete_expense(item_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    x = owned_expense(db, user, item_id)
    db.delete(x)
    db.commit()
    return {'ok': True}


@app.post('/api/expenses/{item_id}/clone')
def clone_expense(item_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    source = owned_expense(db, user, item_id)
    suffix = ' (Copy)' if language_for(db, user) == 'en' else ' (Kopie)'
    clone = Expense(
        name=(source.name + suffix)[:160], provider=source.provider, entry_type=(source.entry_type or 'expense'), amount=source.amount, currency=source.currency,
        billing_interval=source.billing_interval, interval_months=source.interval_months,
        minimum_term_months=source.minimum_term_months, renewal_period_months=source.renewal_period_months,
        category_id=source.category_id, account_id=source.account_id, start_date=source.start_date,
        next_due_date=source.next_due_date, contract_end=source.contract_end, cancellation_date=source.cancellation_date,
        cancellation_notice_days=source.cancellation_notice_days, cancelled_on=None, auto_renew=source.auto_renew,
        status='active', essential=source.essential, tags=source.tags, notes=source.notes, created_by=user.id,
    )
    db.add(clone)
    db.flush()
    for p in source.prices:
        db.add(ExpensePrice(expense_id=clone.id, amount=p.amount, valid_from=p.valid_from))
    db.commit()
    db.refresh(clone)
    return expense_dict(clone)


@app.get('/api/dashboard')
def dashboard(ids: str = Query(default=''), user: User = Depends(current_user), db: Session = Depends(get_db)):
    items = [x for x in db.scalars(select(Expense).where(Expense.created_by == user.id)) if is_effectively_active(x)]
    if ids:
        selected = {int(x) for x in ids.split(',') if x.isdigit()}
        items = [x for x in items if x.id in selected]
    rows = [expense_dict(x) for x in items]
    expense_rows = [x for x in rows if x.get('entry_type') != 'income']
    income_rows = [x for x in rows if x.get('entry_type') == 'income']
    monthly_expenses = round(sum(x['monthly_equivalent'] for x in expense_rows), 2)
    yearly_expenses = round(sum(x['yearly_equivalent'] for x in expense_rows), 2)
    monthly_income = round(sum(x['monthly_equivalent'] for x in income_rows), 2)
    yearly_income = round(sum(x['yearly_equivalent'] for x in income_rows), 2)
    monthly = monthly_expenses
    yearly = yearly_expenses
    categories = {}
    category_colors = {}
    for x in rows:
        key = x['category'] or 'Uncategorized'
        categories[key] = round(categories.get(key, 0) + x['monthly_equivalent'], 2)
        category_colors[key] = x.get('category_color') or '#7B8798'
    today = date.today()
    soon = today + timedelta(days=60)
    expiring = [x for x in expense_rows if x['effective_contract_end'] and today <= x['effective_contract_end'] <= soon]
    cancellation = [x for x in expense_rows if x['effective_cancellation_date'] and today <= x['effective_cancellation_date'] <= soon]
    upcoming = [x for x in expense_rows if x['next_due_date'] and today <= x['next_due_date'] <= today + timedelta(days=31)]
    return {'monthly_total': monthly, 'yearly_total': yearly, 'monthly_expenses': monthly_expenses, 'yearly_expenses': yearly_expenses, 'monthly_income': monthly_income, 'yearly_income': yearly_income, 'monthly_delta': round(monthly_income-monthly_expenses,2), 'yearly_delta': round(yearly_income-yearly_expenses,2), 'count': len(rows), 'categories': categories, 'category_colors': category_colors, 'expiring': expiring, 'cancellation_due': cancellation, 'upcoming_payments': upcoming}


@app.get('/api/settings/reminders')
def reminder_settings(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return {'cancellation_reminder_days': reminder_days_for(db, user)}


@app.put('/api/settings/reminders')
def save_reminder_settings(data: ReminderSettingsIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    set_setting_value(db, f'reminders.cancellation_days.user.{user.id}', str(data.cancellation_reminder_days))
    db.commit()
    return {'ok': True}


@app.get('/api/settings/preferences')
def user_preferences(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return {'language': language_for(db, user), 'ai_prompt': ai_prompt_for(db, user), 'theme': theme_for(db, user)}


@app.put('/api/settings/preferences')
def save_user_preferences(data: UserPreferencesIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if data.language is not None:
        set_setting_value(db, f'preferences.language.user.{user.id}', data.language)
    if data.ai_prompt is not None:
        language = data.language or language_for(db, user)
        set_setting_value(db, f'preferences.ai_prompt.user.{user.id}', data.ai_prompt.strip() or (DEFAULT_AI_PROMPT_EN if language == 'en' else DEFAULT_AI_PROMPT_DE))
    if data.theme is not None:
        set_setting_value(db, f'preferences.theme.user.{user.id}', data.theme)
    db.commit()
    return {'ok': True, 'language': language_for(db, user), 'ai_prompt': ai_prompt_for(db, user), 'theme': theme_for(db, user)}


def reminder_event(x: Expense, today: date, days: int):
    until = today + timedelta(days=days)
    row = expense_dict(x, today)
    end = row['effective_contract_end']
    deadline = row['effective_cancellation_date']
    renewed = bool(x.auto_renew and x.contract_end and x.contract_end < today and end and end > x.contract_end)
    due = bool(deadline and today <= deadline <= until)
    extension_risk = bool(due and x.auto_renew)
    if not (due or renewed):
        return None
    if renewed:
        kind, label = 'auto_renewed', 'Automatisch verlängert'
    elif extension_risk:
        kind, label = 'renewal_risk', 'Verlängerung droht'
    else:
        kind, label = 'cancellation_due', 'Kündigungsfrist läuft'
    remaining = (deadline - today).days if deadline else None
    event_key = f"{kind}:{deadline.isoformat() if deadline else '-'}:{end.isoformat() if end else '-'}"
    return {
        'expense_id': x.id, 'name': x.name, 'provider': x.provider, 'kind': kind, 'label': label, 'event_key': event_key,
        'cancellation_date': deadline, 'contract_end': end, 'days_remaining': remaining, 'cancelled_on': x.cancelled_on,
        'auto_renew': x.auto_renew, 'renewal_period_months': x.renewal_period_months,
        'category': x.category.name if x.category else None, 'category_color': x.category.color if x.category else '#7B8798',
    }


def reminder_action_for(db: Session, user: User, expense_id: int, event_key: str):
    return db.scalar(select(ReminderAction).where(
        ReminderAction.expense_id == expense_id,
        ReminderAction.event_key == event_key,
        ReminderAction.created_by == user.id,
    ).order_by(ReminderAction.id.desc()))


def save_reminder_action(db: Session, expense_id: int, event_key: str, action: str, user_id: int, snooze_until: date | None = None):
    row = db.scalar(select(ReminderAction).where(
        ReminderAction.expense_id == expense_id,
        ReminderAction.event_key == event_key,
        ReminderAction.created_by == user_id,
    ).order_by(ReminderAction.id.desc()))
    if row:
        row.action = action
        row.snooze_until = snooze_until
        row.updated_at = datetime.utcnow()
    else:
        db.add(ReminderAction(expense_id=expense_id, event_key=event_key, action=action, snooze_until=snooze_until, created_by=user_id))


@app.get('/api/reminders')
def reminders(user: User = Depends(current_user), db: Session = Depends(get_db)):
    today = date.today()
    days = reminder_days_for(db, user)
    result = []
    for x in db.scalars(select(Expense).where(Expense.created_by == user.id, Expense.entry_type == 'expense').order_by(Expense.name)):
        if not is_effectively_active(x, today):
            continue
        item = reminder_event(x, today, days)
        if not item:
            continue
        state = reminder_action_for(db, user, x.id, item['event_key'])
        if state:
            if state.action in {'done', 'cancelled'}:
                continue
            if state.action == 'snooze' and state.snooze_until and state.snooze_until > today:
                continue
        result.append(item)
    result.sort(key=lambda r: (r['cancellation_date'] or date.max, r['name'].lower()))
    return {'count': len(result), 'reminder_days': days, 'items': result}


@app.post('/api/reminders/{expense_id}/action')
def reminder_action(expense_id: int, data: ReminderActionIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    x = owned_expense(db, user, expense_id)
    today = date.today()
    days = reminder_days_for(db, user)
    current = reminder_event(x, today, days)
    if not current or current['event_key'] != data.event_key:
        raise HTTPException(409, 'Reminder changed; refresh and try again')
    if data.action == 'snooze':
        if current['cancellation_date'] and current['cancellation_date'] <= today:
            raise HTTPException(400, 'The cancellation deadline has been reached; this reminder cannot be snoozed')
        snooze_until = today + timedelta(days=data.snooze_days or 7)
        if current['cancellation_date'] and snooze_until > current['cancellation_date']:
            snooze_until = current['cancellation_date']
        save_reminder_action(db, x.id, current['event_key'], 'snooze', user.id, snooze_until)
    elif data.action == 'done':
        save_reminder_action(db, x.id, current['event_key'], 'done', user.id)
    else:
        effective_end = current['contract_end']
        if effective_end:
            x.contract_end = effective_end
        x.auto_renew = False
        x.cancelled_on = today
        updated = reminder_event(x, today, days)
        event_key = updated['event_key'] if updated else current['event_key']
        save_reminder_action(db, x.id, event_key, 'cancelled', user.id)
        if event_key != current['event_key']:
            save_reminder_action(db, x.id, current['event_key'], 'cancelled', user.id)
    db.commit()
    return {'ok': True}


def _iso(value):
    return value.isoformat() if value is not None else None


def _date(value):
    if value in (None, ''):
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    return date.fromisoformat(str(value)[:10])


def _datetime(value):
    if value in (None, ''):
        return datetime.utcnow()
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value).replace('Z', '+00:00')).replace(tzinfo=None)


def _raw_expense(x: Expense) -> dict[str, Any]:
    return {
        'id': x.id, 'name': x.name, 'provider': x.provider, 'entry_type': (x.entry_type or 'expense'), 'amount': x.amount, 'currency': x.currency,
        'billing_interval': x.billing_interval, 'interval_months': x.interval_months,
        'minimum_term_months': x.minimum_term_months, 'renewal_period_months': x.renewal_period_months,
        'category_id': x.category_id, 'category_name': x.category.name if x.category else None,
        'account_id': x.account_id, 'account_name': x.account.name if x.account else None,
        'start_date': _iso(x.start_date), 'next_due_date': _iso(x.next_due_date),
        'contract_end': _iso(x.contract_end), 'cancellation_date': _iso(x.cancellation_date),
        'cancellation_notice_days': x.cancellation_notice_days, 'cancelled_on': _iso(x.cancelled_on),
        'auto_renew': x.auto_renew, 'status': x.status, 'essential': x.essential,
        'tags': x.tags, 'notes': x.notes, 'created_by': x.created_by,
        'created_at': _iso(x.created_at), 'updated_at': _iso(x.updated_at),
        'prices': [{'id': p.id, 'amount': p.amount, 'valid_from': _iso(p.valid_from), 'created_at': _iso(p.created_at)} for p in x.prices],
    }


def _new_expense_from_export(row: dict, user_id: int, category_id: int | None, account_id: int | None) -> Expense:
    return Expense(
        name=str(row.get('name') or 'Imported entry')[:160], provider=str(row.get('provider') or '')[:160],
        entry_type=('income' if row.get('entry_type') == 'income' else 'expense'),
        amount=float(row.get('amount') or 0), currency=str(row.get('currency') or 'EUR')[:8],
        billing_interval=str(row.get('billing_interval') or 'monthly')[:20], interval_months=max(1, int(row.get('interval_months') or 1)),
        minimum_term_months=row.get('minimum_term_months'), renewal_period_months=row.get('renewal_period_months'),
        category_id=category_id, account_id=account_id, start_date=_date(row.get('start_date')), next_due_date=_date(row.get('next_due_date')),
        contract_end=_date(row.get('contract_end')), cancellation_date=_date(row.get('cancellation_date')),
        cancellation_notice_days=row.get('cancellation_notice_days'), cancelled_on=_date(row.get('cancelled_on')),
        auto_renew=bool(row.get('auto_renew', False)), status=str(row.get('status') or 'active')[:20],
        essential=bool(row.get('essential', False)), tags=str(row.get('tags') or '')[:255], notes=str(row.get('notes') or ''),
        created_by=user_id, created_at=_datetime(row.get('created_at')), updated_at=_datetime(row.get('updated_at')),
    )


@app.get('/api/export/user')
def export_user_data(user: User = Depends(current_user), db: Session = Depends(get_db)):
    hidden_rows = list(db.scalars(select(HiddenCatalogItem).where(HiddenCatalogItem.user_id == user.id)))
    hidden_accounts, hidden_categories = [], []
    for row in hidden_rows:
        if row.item_type == 'account':
            item = db.get(Account, row.item_id)
            if item: hidden_accounts.append(item.name)
        elif row.item_type == 'category':
            item = db.get(Category, row.item_id)
            if item: hidden_categories.append(item.name)
    expenses = list(db.scalars(select(Expense).where(Expense.created_by == user.id).order_by(Expense.id)))
    reminders = list(db.scalars(select(ReminderAction).where(ReminderAction.created_by == user.id).order_by(ReminderAction.id)))
    conversations = list(db.scalars(select(AIConversation).where(AIConversation.user_id == user.id).order_by(AIConversation.id)))
    brain = db.get(AIBrain, user.id)
    return {
        'format': 'pengucost-user-export', 'schema_version': 2, 'app_version': APP_VERSION,
        'exported_at': datetime.utcnow().isoformat() + 'Z',
        'user': {'username': user.username, 'display_name': user.display_name},
        'preferences': {'language': language_for(db, user), 'ai_prompt': ai_prompt_for(db, user), 'theme': theme_for(db, user), 'cancellation_reminder_days': reminder_days_for(db, user)},
        'hidden_catalog': {'accounts': sorted(hidden_accounts), 'categories': sorted(hidden_categories)},
        'expenses': [_raw_expense(x) for x in expenses],
        'reminder_actions': [{'expense_id': r.expense_id, 'event_key': r.event_key, 'action': r.action, 'snooze_until': _iso(r.snooze_until), 'created_at': _iso(r.created_at), 'updated_at': _iso(r.updated_at)} for r in reminders],
        'ai_brain': {'summary': brain.summary, 'updated_at': _iso(brain.updated_at)} if brain else None,
        'ai_conversations': [{**_conversation_dict(c, db, True), 'profile_name': (db.get(AIProfile, c.profile_id).name if c.profile_id and db.get(AIProfile, c.profile_id) else None)} for c in conversations],
    }


@app.post('/api/import/user')
def import_user_data(payload: dict, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if payload.get('format') != 'pengucost-user-export':
        raise HTTPException(400, 'Not a PenguCost user export')
    expenses_in = payload.get('expenses') or []
    if not isinstance(expenses_in, list):
        raise HTTPException(400, 'Invalid expenses payload')
    # Replace only this user's private data. Global admin catalogs and every other user's data remain untouched.
    for c in list(db.scalars(select(AIConversation).where(AIConversation.user_id == user.id))):
        for m in list(db.scalars(select(AIMessage).where(AIMessage.conversation_id == c.id))): db.delete(m)
        db.delete(c)
    old_brain = db.get(AIBrain, user.id)
    if old_brain: db.delete(old_brain)
    expense_ids = list(db.scalars(select(Expense.id).where(Expense.created_by == user.id)))
    if expense_ids:
        for r in list(db.scalars(select(ReminderAction).where(ReminderAction.created_by == user.id))): db.delete(r)
        for x in list(db.scalars(select(Expense).where(Expense.created_by == user.id))): db.delete(x)
    for h in list(db.scalars(select(HiddenCatalogItem).where(HiddenCatalogItem.user_id == user.id))): db.delete(h)
    db.flush()

    categories_by_name = {x.name: x.id for x in db.scalars(select(Category))}
    accounts_by_name = {x.name: x.id for x in db.scalars(select(Account))}
    warnings: list[str] = []
    id_map: dict[int, int] = {}
    for row in expenses_in:
        cat_name, account_name = row.get('category_name'), row.get('account_name')
        category_id = categories_by_name.get(cat_name) if cat_name else None
        account_id = accounts_by_name.get(account_name) if account_name else None
        if cat_name and category_id is None: warnings.append(f'Unknown category: {cat_name}')
        if account_name and account_id is None: warnings.append(f'Unknown account: {account_name}')
        x = _new_expense_from_export(row, user.id, category_id, account_id)
        db.add(x); db.flush()
        old_id = int(row.get('id') or 0)
        if old_id: id_map[old_id] = x.id
        prices = row.get('prices') or []
        if prices:
            for p in prices:
                db.add(ExpensePrice(expense_id=x.id, amount=float(p.get('amount') or 0), valid_from=_date(p.get('valid_from')) or date.today(), created_at=_datetime(p.get('created_at'))))
        else:
            db.add(ExpensePrice(expense_id=x.id, amount=x.amount, valid_from=x.start_date or date.today()))

    hidden = payload.get('hidden_catalog') or {}
    for name in hidden.get('accounts') or []:
        item_id = accounts_by_name.get(name)
        if item_id: hide_catalog_item(db, user, 'account', item_id)
    for name in hidden.get('categories') or []:
        item_id = categories_by_name.get(name)
        if item_id: hide_catalog_item(db, user, 'category', item_id)

    pref = payload.get('preferences') or {}
    language = pref.get('language') if pref.get('language') in {'de', 'en'} else 'de'
    set_setting_value(db, f'preferences.language.user.{user.id}', language)
    set_setting_value(db, f'preferences.ai_prompt.user.{user.id}', str(pref.get('ai_prompt') or (DEFAULT_AI_PROMPT_EN if language == 'en' else DEFAULT_AI_PROMPT_DE)))
    theme = pref.get('theme') if pref.get('theme') in {'system', 'light', 'midnight', 'nordic', 'graphite', 'emerald'} else 'system'
    set_setting_value(db, f'preferences.theme.user.{user.id}', theme)
    try: reminder_days = min(3650, max(0, int(pref.get('cancellation_reminder_days', 30))))
    except Exception: reminder_days = 30
    set_setting_value(db, f'reminders.cancellation_days.user.{user.id}', str(reminder_days))

    for r in payload.get('reminder_actions') or []:
        new_expense_id = id_map.get(int(r.get('expense_id') or 0))
        if new_expense_id:
            db.add(ReminderAction(expense_id=new_expense_id, event_key=str(r.get('event_key') or '')[:160], action=str(r.get('action') or 'done')[:20], snooze_until=_date(r.get('snooze_until')), created_by=user.id, created_at=_datetime(r.get('created_at')), updated_at=_datetime(r.get('updated_at'))))
    brain = payload.get('ai_brain')
    if isinstance(brain, dict) and brain.get('summary'):
        db.add(AIBrain(user_id=user.id, summary=str(brain.get('summary') or '')[:12000], updated_at=_datetime(brain.get('updated_at'))))
    profile_by_name = {x.name: x.id for x in db.scalars(select(AIProfile))}
    for c in payload.get('ai_conversations') or []:
        selected_ids = [id_map[int(i)] for i in (c.get('selected_expense_ids') or []) if str(i).isdigit() and int(i) in id_map]
        profile_id = profile_by_name.get(c.get('profile_name')) if c.get('profile_name') else None
        conv = AIConversation(user_id=user.id, profile_id=profile_id, title=str(c.get('title') or 'PenguCost AI')[:180], mode=str(c.get('mode') or 'analysis')[:24], target_savings=c.get('target_savings'), selected_expense_ids=json.dumps(selected_ids), status='idle', last_error='', created_at=_datetime(c.get('created_at')), updated_at=_datetime(c.get('updated_at')))
        db.add(conv); db.flush()
        for m in c.get('messages') or []:
            db.add(AIMessage(conversation_id=conv.id, role=str(m.get('role') or 'user')[:20], content=str(m.get('content') or ''), created_at=_datetime(m.get('created_at'))))
    db.commit()
    return {'ok': True, 'imported_expenses': len(expenses_in), 'warnings': sorted(set(warnings))}


@app.get('/api/export/admin')
def export_admin_data(_: User = Depends(require_admin), db: Session = Depends(get_db)):
    users = list(db.scalars(select(User).order_by(User.id)))
    accounts = list(db.scalars(select(Account).order_by(Account.id)))
    categories = list(db.scalars(select(Category).order_by(Category.id)))
    expenses = list(db.scalars(select(Expense).order_by(Expense.id)))
    return {
        'format': 'pengucost-admin-export', 'schema_version': 2, 'app_version': APP_VERSION,
        'exported_at': datetime.utcnow().isoformat() + 'Z',
        'users': [{'id': u.id, 'username': u.username, 'display_name': u.display_name, 'password_hash': u.password_hash, 'role': u.role, 'is_active': u.is_active, 'created_at': _iso(u.created_at)} for u in users],
        'accounts': [{'id': x.id, 'name': x.name, 'kind': x.kind, 'note': x.note} for x in accounts],
        'categories': [{'id': x.id, 'name': x.name, 'icon': x.icon, 'color': x.color} for x in categories],
        'hidden_catalog_items': [{'id': x.id, 'user_id': x.user_id, 'item_type': x.item_type, 'item_id': x.item_id, 'created_at': _iso(x.created_at)} for x in db.scalars(select(HiddenCatalogItem).order_by(HiddenCatalogItem.id))],
        'expenses': [_raw_expense(x) for x in expenses],
        'reminder_actions': [{'id': r.id, 'expense_id': r.expense_id, 'event_key': r.event_key, 'action': r.action, 'snooze_until': _iso(r.snooze_until), 'created_by': r.created_by, 'created_at': _iso(r.created_at), 'updated_at': _iso(r.updated_at)} for r in db.scalars(select(ReminderAction).order_by(ReminderAction.id))],
        'ai_profiles': [{'id': x.id, 'name': x.name, 'provider': x.provider, 'base_url': x.base_url, 'model': x.model, 'api_key': decrypt_secret(x.api_key), 'enabled': x.enabled, 'created_at': _iso(x.created_at), 'updated_at': _iso(x.updated_at)} for x in db.scalars(select(AIProfile).order_by(AIProfile.id))],
        'ai_conversations': [{**_conversation_dict(x, db, True), 'user_id': x.user_id} for x in db.scalars(select(AIConversation).order_by(AIConversation.id))],
        'ai_brains': [{'user_id': x.user_id, 'summary': x.summary, 'updated_at': _iso(x.updated_at)} for x in db.scalars(select(AIBrain).order_by(AIBrain.user_id))],
        'settings': [{'key': x.key, 'value': x.value} for x in db.scalars(select(Setting).order_by(Setting.key))],
    }


@app.post('/api/import/admin')
def import_admin_data(payload: dict, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    session_admin_id = admin.id
    if payload.get('format') != 'pengucost-admin-export':
        raise HTTPException(400, 'Not a PenguCost admin export')
    users_in = payload.get('users') or []
    if not any(u.get('role') == 'admin' and u.get('is_active', True) for u in users_in):
        raise HTTPException(400, 'Import must contain at least one active administrator')
    # Destructive full restore. Order matters because expenses reference catalogs/users.
    # Detach the authenticated admin object so an imported user with the same primary key can be inserted cleanly.
    db.expunge(admin)
    for table in ('ai_messages', 'ai_conversations', 'ai_brains', 'reminder_actions', 'expense_prices', 'expenses', 'hidden_catalog_items', 'ai_profiles', 'settings', 'categories', 'accounts', 'users'):
        db.execute(text(f'DELETE FROM {table}'))
    db.flush()
    for u in users_in:
        db.add(User(id=int(u['id']), username=str(u['username']), display_name=str(u.get('display_name') or ''), password_hash=str(u['password_hash']), role=str(u.get('role') or 'member'), is_active=bool(u.get('is_active', True)), created_at=_datetime(u.get('created_at'))))
    for x in payload.get('accounts') or []:
        db.add(Account(id=int(x['id']), name=str(x['name']), kind=str(x.get('kind') or 'bank'), note=str(x.get('note') or '')))
    for x in payload.get('categories') or []:
        db.add(Category(id=int(x['id']), name=str(x['name']), icon=str(x.get('icon') or 'wallet'), color=str(x.get('color') or '#5B5CF0')))
    db.flush()
    for row in payload.get('expenses') or []:
        x = _new_expense_from_export(row, int(row.get('created_by')), row.get('category_id'), row.get('account_id'))
        x.id = int(row['id']); db.add(x); db.flush()
        for p in row.get('prices') or []:
            db.add(ExpensePrice(id=int(p['id']), expense_id=x.id, amount=float(p.get('amount') or 0), valid_from=_date(p.get('valid_from')) or date.today(), created_at=_datetime(p.get('created_at'))))
    for x in payload.get('hidden_catalog_items') or []:
        db.add(HiddenCatalogItem(id=int(x['id']), user_id=int(x['user_id']), item_type=str(x['item_type']), item_id=int(x['item_id']), created_at=_datetime(x.get('created_at'))))
    for r in payload.get('reminder_actions') or []:
        db.add(ReminderAction(id=int(r['id']), expense_id=int(r['expense_id']), event_key=str(r.get('event_key') or ''), action=str(r.get('action') or 'done'), snooze_until=_date(r.get('snooze_until')), created_by=r.get('created_by'), created_at=_datetime(r.get('created_at')), updated_at=_datetime(r.get('updated_at'))))
    for x in payload.get('ai_profiles') or []:
        db.add(AIProfile(id=int(x['id']), name=str(x.get('name') or 'AI'), provider=str(x.get('provider') or 'custom'), base_url=str(x.get('base_url') or ''), model=str(x.get('model') or ''), api_key=encrypt_secret(str(x.get('api_key') or '')), enabled=bool(x.get('enabled', True)), created_at=_datetime(x.get('created_at')), updated_at=_datetime(x.get('updated_at'))))
    db.flush()
    for x in payload.get('ai_conversations') or []:
        conv = AIConversation(id=int(x['id']), user_id=int(x['user_id']), profile_id=x.get('profile_id'), title=str(x.get('title') or 'PenguCost AI')[:180], mode=str(x.get('mode') or 'analysis')[:24], target_savings=x.get('target_savings'), selected_expense_ids=json.dumps(x.get('selected_expense_ids') or []), status='idle', last_error='', created_at=_datetime(x.get('created_at')), updated_at=_datetime(x.get('updated_at')))
        db.add(conv); db.flush()
        for m in x.get('messages') or []:
            db.add(AIMessage(id=int(m['id']) if m.get('id') else None, conversation_id=conv.id, role=str(m.get('role') or 'user')[:20], content=str(m.get('content') or ''), created_at=_datetime(m.get('created_at'))))
    for x in payload.get('ai_brains') or []:
        db.add(AIBrain(user_id=int(x['user_id']), summary=str(x.get('summary') or '')[:12000], updated_at=_datetime(x.get('updated_at'))))
    for x in payload.get('settings') or []:
        db.add(Setting(key=str(x['key']), value=str(x.get('value') or '')))
    db.commit()
    return {'ok': True, 'users': len(users_in), 'expenses': len(payload.get('expenses') or []), 'session_user_id': session_admin_id}


@app.get('/api/ai/providers')
def ai_providers(_: User = Depends(current_user)):
    return AI_PROVIDERS


@app.get('/api/ai/profiles')
def ai_profiles(_: User = Depends(current_user), db: Session = Depends(get_db)):
    return [ai_profile_dict(x, admin=False) for x in db.scalars(select(AIProfile).where(AIProfile.enabled == True).order_by(AIProfile.name))]


@app.get('/api/settings/ai/profiles')
def admin_ai_profiles(_: User = Depends(require_admin), db: Session = Depends(get_db)):
    return [ai_profile_dict(x, admin=True) for x in db.scalars(select(AIProfile).order_by(AIProfile.name))]


@app.post('/api/settings/ai/profiles')
def add_ai_profile(data: AIProfileIn, _: User = Depends(require_admin), db: Session = Depends(get_db)):
    defaults = provider_defaults(data.provider)
    x = AIProfile(
        name=data.name.strip(), provider=data.provider,
        base_url=(data.base_url.strip() or defaults['default_base_url']), model=data.model.strip(),
        api_key=encrypt_secret(data.api_key), enabled=data.enabled,
    )
    db.add(x)
    db.commit()
    db.refresh(x)
    return ai_profile_dict(x, admin=True)


@app.put('/api/settings/ai/profiles/{profile_id}')
def update_ai_profile(profile_id: int, data: AIProfilePatch, _: User = Depends(require_admin), db: Session = Depends(get_db)):
    x = db.get(AIProfile, profile_id)
    if not x:
        raise HTTPException(404, 'AI profile not found')
    provider = data.provider if data.provider is not None else x.provider
    defaults = provider_defaults(provider)
    if data.name is not None:
        x.name = data.name.strip()
    if data.provider is not None:
        x.provider = data.provider
    if data.base_url is not None:
        x.base_url = data.base_url.strip() or defaults['default_base_url']
    elif data.provider is not None and not x.base_url:
        x.base_url = defaults['default_base_url']
    if data.model is not None:
        x.model = data.model.strip()
    if data.api_key:
        x.api_key = encrypt_secret(data.api_key)
    if data.enabled is not None:
        x.enabled = data.enabled
    db.commit()
    db.refresh(x)
    return ai_profile_dict(x, admin=True)


@app.delete('/api/settings/ai/profiles/{profile_id}')
def delete_ai_profile(profile_id: int, _: User = Depends(require_admin), db: Session = Depends(get_db)):
    x = db.get(AIProfile, profile_id)
    if not x:
        raise HTTPException(404, 'AI profile not found')
    db.delete(x)
    db.commit()
    return {'ok': True}


def _json_ids(value: str) -> list[int]:
    try:
        raw = json.loads(value or '[]')
        return [int(x) for x in raw if str(x).isdigit()]
    except Exception:
        return []


def _conversation_dict(x: AIConversation, db: Session, include_messages: bool = False) -> dict[str, Any]:
    data = {
        'id': x.id, 'profile_id': x.profile_id, 'title': x.title, 'mode': x.mode,
        'target_savings': x.target_savings, 'selected_expense_ids': _json_ids(x.selected_expense_ids),
        'status': x.status, 'last_error': x.last_error, 'created_at': _iso(x.created_at), 'updated_at': _iso(x.updated_at),
    }
    if include_messages:
        data['messages'] = [
            {'id': m.id, 'role': m.role, 'content': m.content, 'created_at': _iso(m.created_at)}
            for m in db.scalars(select(AIMessage).where(AIMessage.conversation_id == x.id).order_by(AIMessage.id))
        ]
    return data


def _owned_conversation(db: Session, user_id: int, conversation_id: int) -> AIConversation:
    x = db.get(AIConversation, conversation_id)
    if not x or x.user_id != user_id:
        raise HTTPException(404, 'AI conversation not found')
    return x


def _ai_finance_payload(db: Session, user_id: int, requested_ids: list[int]) -> dict[str, Any]:
    entries = [x for x in db.scalars(select(Expense).where(Expense.created_by == user_id)) if is_effectively_active(x)]
    if requested_ids:
        selected = set(requested_ids)
        entries = [x for x in entries if x.id in selected]
    rows = [expense_dict(x) for x in entries]
    expense_rows = [x for x in rows if x.get('entry_type') != 'income']
    income_rows = [x for x in rows if x.get('entry_type') == 'income']
    monthly_expenses = round(sum(x['monthly_equivalent'] for x in expense_rows), 2)
    monthly_income = round(sum(x['monthly_equivalent'] for x in income_rows), 2)
    return {
        'monthly_expenses': monthly_expenses,
        'yearly_expenses': round(sum(x['yearly_equivalent'] for x in expense_rows), 2),
        'monthly_income': monthly_income,
        'yearly_income': round(sum(x['yearly_equivalent'] for x in income_rows), 2),
        'monthly_delta': round(monthly_income - monthly_expenses, 2),
        'entries': rows,
    }


def _update_brain_memory(db: Session, user_id: int, mode: str, target: float | None, user_message: str, assistant_message: str):
    row = db.get(AIBrain, user_id)
    if not row:
        row = AIBrain(user_id=user_id, summary='')
        db.add(row)
    stamp = date.today().isoformat()
    goal = f' | Sparziel {target:.2f} EUR/Monat' if target is not None else ''
    question = ' '.join(user_message.strip().split())[:280]
    answer = ' '.join(assistant_message.replace('#', ' ').replace('*', ' ').split())[:520]
    entry = f'{stamp} | {mode}{goal}\nFrage: {question}\nErkenntnis: {answer}'
    previous = [x.strip() for x in (row.summary or '').split('\n\n') if x.strip()]
    row.summary = '\n\n'.join((previous + [entry])[-8:])[-8000:]
    row.updated_at = datetime.utcnow()


async def _run_ai_conversation_turn(conversation_id: int, user_id: int, user_message: str, language: str):
    db = SessionLocal()
    try:
        conv = db.get(AIConversation, conversation_id)
        if not conv or conv.user_id != user_id:
            return
        profile = db.get(AIProfile, conv.profile_id) if conv.profile_id else db.scalar(select(AIProfile).where(AIProfile.enabled == True).order_by(AIProfile.id))
        if not profile or not profile.enabled:
            conv.status = 'error'; conv.last_error = 'No enabled AI profile is available'; db.commit(); return
        finance = _ai_finance_payload(db, user_id, _json_ids(conv.selected_expense_ids))
        brain = db.get(AIBrain, user_id)
        history_rows = list(db.scalars(select(AIMessage).where(AIMessage.conversation_id == conversation_id).order_by(AIMessage.id)))
        # The newest user message is supplied separately to avoid sending it twice.
        history = [{'role': m.role, 'content': m.content} for m in history_rows[:-1] if m.role in {'user', 'assistant'}]
        reply = await chat_finances(
            profile.provider, profile.base_url, decrypt_secret(profile.api_key), profile.model,
            finance, brain.summary if brain else '', history, user_message, language,
            conv.mode, conv.target_savings,
        )
        db.add(AIMessage(conversation_id=conversation_id, role='assistant', content=reply))
        conv.status = 'idle'; conv.last_error = ''; conv.updated_at = datetime.utcnow()
        _update_brain_memory(db, user_id, conv.mode, conv.target_savings, user_message, reply)
        db.commit()
    except Exception as e:
        try:
            conv = db.get(AIConversation, conversation_id)
            if conv:
                conv.status = 'error'; conv.last_error = str(e)[:2000]; conv.updated_at = datetime.utcnow(); db.commit()
        except Exception:
            db.rollback()
    finally:
        db.close()


@app.get('/api/ai/conversations')
def ai_conversations(user: User = Depends(current_user), db: Session = Depends(get_db)):
    rows = db.scalars(select(AIConversation).where(AIConversation.user_id == user.id).order_by(AIConversation.updated_at.desc(), AIConversation.id.desc()))
    return [_conversation_dict(x, db, False) for x in rows]


@app.post('/api/ai/conversations')
def create_ai_conversation(data: AIConversationIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    profile = db.get(AIProfile, data.profile_id) if data.profile_id else db.scalar(select(AIProfile).where(AIProfile.enabled == True).order_by(AIProfile.id))
    if not profile or not profile.enabled:
        raise HTTPException(400, 'No enabled AI profile is available')
    owned_ids = set(db.scalars(select(Expense.id).where(Expense.created_by == user.id)))
    selected_ids = [x for x in data.expense_ids if x in owned_ids]
    label = data.title or ('Sparziel' if data.mode == 'savings' else 'Kostencheck' if data.mode == 'analysis' else 'PenguCost Chat')
    x = AIConversation(user_id=user.id, profile_id=profile.id, title=label[:180], mode=data.mode, target_savings=data.target_savings, selected_expense_ids=json.dumps(selected_ids), status='idle')
    db.add(x); db.commit(); db.refresh(x)
    return _conversation_dict(x, db, True)


@app.get('/api/ai/conversations/{conversation_id}')
def get_ai_conversation(conversation_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return _conversation_dict(_owned_conversation(db, user.id, conversation_id), db, True)


@app.delete('/api/ai/conversations/{conversation_id}')
def delete_ai_conversation(conversation_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    x = _owned_conversation(db, user.id, conversation_id)
    if x.status == 'running':
        raise HTTPException(409, 'AI conversation is still running')
    for m in list(db.scalars(select(AIMessage).where(AIMessage.conversation_id == x.id))):
        db.delete(m)
    db.delete(x); db.commit()
    return {'ok': True}


@app.post('/api/ai/conversations/{conversation_id}/messages')
def send_ai_message(conversation_id: int, data: AIChatIn, background_tasks: BackgroundTasks, user: User = Depends(current_user), db: Session = Depends(get_db)):
    x = _owned_conversation(db, user.id, conversation_id)
    if x.status == 'running':
        raise HTTPException(409, 'AI conversation is already running')
    if data.profile_id is not None:
        p = db.get(AIProfile, data.profile_id)
        if not p or not p.enabled:
            raise HTTPException(400, 'AI profile is not enabled')
        x.profile_id = p.id
    owned_ids = set(db.scalars(select(Expense.id).where(Expense.created_by == user.id)))
    if data.expense_ids:
        x.selected_expense_ids = json.dumps([i for i in data.expense_ids if i in owned_ids])
    if data.mode is not None:
        x.mode = data.mode
    if data.target_savings is not None or x.mode != 'savings':
        x.target_savings = data.target_savings
    db.add(AIMessage(conversation_id=x.id, role='user', content=data.message.strip()))
    if len(list(db.scalars(select(AIMessage.id).where(AIMessage.conversation_id == x.id)))) <= 1:
        clean = ' '.join(data.message.strip().split())
        x.title = clean[:72] + ('…' if len(clean) > 72 else '')
    x.status = 'running'; x.last_error = ''; x.updated_at = datetime.utcnow()
    db.commit()
    background_tasks.add_task(_run_ai_conversation_turn, x.id, user.id, data.message.strip(), data.language)
    return _conversation_dict(x, db, True)


@app.get('/api/ai/brain')
def get_ai_brain(user: User = Depends(current_user), db: Session = Depends(get_db)):
    x = db.get(AIBrain, user.id)
    return {'summary': x.summary if x else '', 'updated_at': _iso(x.updated_at) if x else None}


@app.put('/api/ai/brain')
def put_ai_brain(data: AIBrainIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    x = db.get(AIBrain, user.id)
    if not x:
        x = AIBrain(user_id=user.id, summary=data.summary.strip())
        db.add(x)
    else:
        x.summary = data.summary.strip(); x.updated_at = datetime.utcnow()
    db.commit()
    return {'summary': x.summary, 'updated_at': _iso(x.updated_at)}


@app.post('/api/ai/analyze')
async def ai_analyze(data: AIAnalyzeIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    profile = db.get(AIProfile, data.profile_id) if data.profile_id else db.scalar(select(AIProfile).where(AIProfile.enabled == True).order_by(AIProfile.id))
    if not profile or not profile.enabled:
        raise HTTPException(400, 'No enabled AI profile is available')
    rows = [expense_dict(x) for x in db.scalars(select(Expense).where(Expense.created_by == user.id)) if is_effectively_active(x)]
    if data.expense_ids:
        selected = set(data.expense_ids)
        rows = [x for x in rows if x['id'] in selected]
    expense_rows = [x for x in rows if x.get('entry_type') != 'income']
    income_rows = [x for x in rows if x.get('entry_type') == 'income']
    monthly_expenses = round(sum(x['monthly_equivalent'] for x in expense_rows), 2)
    monthly_income = round(sum(x['monthly_equivalent'] for x in income_rows), 2)
    summary = {
        'monthly_expenses': monthly_expenses,
        'yearly_expenses': round(sum(x['yearly_equivalent'] for x in expense_rows), 2),
        'monthly_income': monthly_income,
        'yearly_income': round(sum(x['yearly_equivalent'] for x in income_rows), 2),
        'monthly_delta': round(monthly_income - monthly_expenses, 2),
        'entries': rows,
    }
    try:
        result = await analyze_costs(profile.provider, profile.base_url, decrypt_secret(profile.api_key), profile.model, summary, data.goal or ai_prompt_for(db, user), data.language if data.language in {'de', 'en'} else language_for(db, user))
        return {'analysis': result, 'profile': ai_profile_dict(profile, admin=False)}
    except Exception as e:
        raise HTTPException(502, f'AI request failed: {e}')


STATIC_DIR = Path(__file__).parent / 'static'
if STATIC_DIR.exists():
    app.mount('/assets', StaticFiles(directory=STATIC_DIR / 'assets'), name='assets')

    @app.get('/{full_path:path}')
    def spa(full_path: str):
        candidate = STATIC_DIR / full_path
        if full_path and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(STATIC_DIR / 'index.html')
