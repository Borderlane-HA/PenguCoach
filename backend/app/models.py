from datetime import datetime, date
from sqlalchemy import String, Float, Boolean, Date, DateTime, ForeignKey, Integer, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .db import Base


class User(Base):
    __tablename__ = 'users'
    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(120), default='')
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(20), default='member')
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Account(Base):
    __tablename__ = 'accounts'
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True)
    kind: Mapped[str] = mapped_column(String(40), default='bank')
    note: Mapped[str] = mapped_column(String(255), default='')


class Category(Base):
    __tablename__ = 'categories'
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    icon: Mapped[str] = mapped_column(String(40), default='wallet')
    color: Mapped[str] = mapped_column(String(16), default='#5B5CF0')


class HiddenCatalogItem(Base):
    __tablename__ = 'hidden_catalog_items'
    __table_args__ = (UniqueConstraint('user_id', 'item_type', 'item_id', name='uq_hidden_catalog_item'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id'), index=True)
    item_type: Mapped[str] = mapped_column(String(20), index=True)
    item_id: Mapped[int] = mapped_column(Integer, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Expense(Base):
    __tablename__ = 'expenses'
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(160), index=True)
    provider: Mapped[str] = mapped_column(String(160), default='')
    entry_type: Mapped[str] = mapped_column(String(16), default='expense', index=True)
    amount: Mapped[float] = mapped_column(Float)
    currency: Mapped[str] = mapped_column(String(8), default='EUR')
    billing_interval: Mapped[str] = mapped_column(String(20), default='monthly')
    interval_months: Mapped[int] = mapped_column(Integer, default=1)
    minimum_term_months: Mapped[int | None] = mapped_column(Integer, nullable=True)
    renewal_period_months: Mapped[int | None] = mapped_column(Integer, nullable=True)
    category_id: Mapped[int | None] = mapped_column(ForeignKey('categories.id'), nullable=True)
    account_id: Mapped[int | None] = mapped_column(ForeignKey('accounts.id'), nullable=True)
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    next_due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    contract_end: Mapped[date | None] = mapped_column(Date, nullable=True)
    cancellation_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    cancellation_notice_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cancelled_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    auto_renew: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(20), default='active')
    essential: Mapped[bool] = mapped_column(Boolean, default=False)
    tags: Mapped[str] = mapped_column(String(255), default='')
    notes: Mapped[str] = mapped_column(Text, default='')
    created_by: Mapped[int | None] = mapped_column(ForeignKey('users.id'), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    category = relationship(Category)
    account = relationship(Account)
    prices = relationship('ExpensePrice', back_populates='expense', cascade='all, delete-orphan', order_by='ExpensePrice.valid_from')


class ExpensePrice(Base):
    __tablename__ = 'expense_prices'
    id: Mapped[int] = mapped_column(primary_key=True)
    expense_id: Mapped[int] = mapped_column(ForeignKey('expenses.id'), index=True)
    amount: Mapped[float] = mapped_column(Float)
    valid_from: Mapped[date] = mapped_column(Date, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    expense = relationship(Expense, back_populates='prices')


class ReminderAction(Base):
    __tablename__ = 'reminder_actions'
    id: Mapped[int] = mapped_column(primary_key=True)
    expense_id: Mapped[int] = mapped_column(ForeignKey('expenses.id'), index=True)
    event_key: Mapped[str] = mapped_column(String(160), index=True)
    action: Mapped[str] = mapped_column(String(20))
    snooze_until: Mapped[date | None] = mapped_column(Date, nullable=True)
    created_by: Mapped[int | None] = mapped_column(ForeignKey('users.id'), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class AIProfile(Base):
    __tablename__ = 'ai_profiles'
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), default='AI')
    provider: Mapped[str] = mapped_column(String(40), default='custom')
    base_url: Mapped[str] = mapped_column(String(500), default='')
    model: Mapped[str] = mapped_column(String(200), default='')
    api_key: Mapped[str] = mapped_column(Text, default='')
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class AIConversation(Base):
    __tablename__ = 'ai_conversations'
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id'), index=True)
    profile_id: Mapped[int | None] = mapped_column(ForeignKey('ai_profiles.id'), nullable=True, index=True)
    title: Mapped[str] = mapped_column(String(180), default='PenguCost AI')
    mode: Mapped[str] = mapped_column(String(24), default='analysis')
    target_savings: Mapped[float | None] = mapped_column(Float, nullable=True)
    selected_expense_ids: Mapped[str] = mapped_column(Text, default='[]')
    status: Mapped[str] = mapped_column(String(20), default='idle', index=True)
    last_error: Mapped[str] = mapped_column(Text, default='')
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class AIMessage(Base):
    __tablename__ = 'ai_messages'
    id: Mapped[int] = mapped_column(primary_key=True)
    conversation_id: Mapped[int] = mapped_column(ForeignKey('ai_conversations.id'), index=True)
    role: Mapped[str] = mapped_column(String(20), default='user')
    content: Mapped[str] = mapped_column(Text, default='')
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


class AIBrain(Base):
    __tablename__ = 'ai_brains'
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id'), primary_key=True)
    summary: Mapped[str] = mapped_column(Text, default='')
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Setting(Base):
    __tablename__ = 'settings'
    key: Mapped[str] = mapped_column(String(120), primary_key=True)
    value: Mapped[str] = mapped_column(Text, default='')
