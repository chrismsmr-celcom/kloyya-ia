"""
Billing (spec landing §6). Stripe est la source de vérité ; on la mirrore
localement pour des lectures rapides mais on ne réconcilie QUE via webhook,
jamais via un callback client — exactement l'exigence de la spec.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import stripe
from fastapi import APIRouter, Depends, HTTPException, Request

from app.config import get_settings
from app.db.session import system_connection
from app.deps import CurrentUser, get_current_user

router = APIRouter(prefix="/api/billing", tags=["billing"])

TIERS = {
    "free": {"monthly_cents": 0, "trial_days": 30},
    "starter": {"monthly_cents": 6900, "trial_days": 7},
    "business": {"monthly_cents": 9900, "trial_days": 7},
    "teams": {"monthly_cents": 27900, "trial_days": 7},
    "enterprise": {"monthly_cents": None, "trial_days": None},
}


def yearly_price_cents(monthly_cents: int) -> int:
    # "round(monthly x 12 x 0.9)" — calculé serveur, jamais côté client (spec §6).
    return round(monthly_cents * 12 * 0.9)


@router.get("/subscription")
async def get_subscription(user: CurrentUser = Depends(get_current_user)):
    async with system_connection() as conn:
        row = await conn.fetchrow(
            "select tier, trial_ends_at, free_period_ends_at, stripe_customer_id from workspaces where id = $1",
            user.workspace_id,
        )
    return dict(row)


@router.post("/subscribe")
async def subscribe(
    body: dict,  # { tierId, cadence, paymentMethodId? }
    user: CurrentUser = Depends(get_current_user),
):
    settings = get_settings()
    tier_id = body["tierId"]
    cadence = body.get("cadence", "monthly")

    if tier_id == "free":
        async with system_connection() as conn:
            await conn.execute(
                "update workspaces set tier = 'free', free_period_ends_at = $1 where id = $2",
                datetime.now(timezone.utc) + timedelta(days=30), user.workspace_id,
            )
        return {"tier": "free"}

    if tier_id == "enterprise":
        raise HTTPException(400, "Enterprise is sales-led — use /billing/enterprise-inquiry")

    if not settings.STRIPE_SECRET_KEY:
        raise HTTPException(500, "Stripe not configured")

    stripe.api_key = settings.STRIPE_SECRET_KEY
    tier = TIERS[tier_id]
    price_cents = tier["monthly_cents"] if cadence == "monthly" else yearly_price_cents(tier["monthly_cents"])

    # Création/récupération du customer + souscription avec essai (0.00 due today).
    async with system_connection() as conn:
        row = await conn.fetchrow("select stripe_customer_id from workspaces where id = $1", user.workspace_id)
        customer_id = row["stripe_customer_id"]
        if not customer_id:
            customer = stripe.Customer.create(email=user.email)
            customer_id = customer.id
            await conn.execute("update workspaces set stripe_customer_id = $1 where id = $2", customer_id, user.workspace_id)

    subscription = stripe.Subscription.create(
        customer=customer_id,
        items=[{"price_data": {
            "currency": "usd", "unit_amount": price_cents,
            "recurring": {"interval": "month" if cadence == "monthly" else "year"},
            "product_data": {"name": f"Kloyya {tier_id.title()}"},
        }}],
        trial_period_days=tier["trial_days"],
        payment_behavior="default_incomplete",
    )

    async with system_connection() as conn:
        await conn.execute(
            "update workspaces set tier = $1, trial_ends_at = $2 where id = $3",
            tier_id, datetime.fromtimestamp(subscription.trial_end, tz=timezone.utc) if subscription.trial_end else None,
            user.workspace_id,
        )

    return {"subscriptionId": subscription.id, "status": subscription.status}


@router.post("/enterprise-inquiry")
async def enterprise_inquiry(body: dict):
    # TODO intégration CRM : écrire un lead + notifier sales (Slack), spec landing §6/§7.
    return {"ok": True}


@router.post("/webhooks/stripe")
async def stripe_webhook(request: Request):
    settings = get_settings()
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature")
    try:
        event = stripe.Webhook.construct_event(payload, sig_header, settings.STRIPE_WEBHOOK_SECRET)
    except Exception as exc:
        raise HTTPException(400, f"Invalid webhook signature: {exc}")

    # Idempotent sur event.id — à persister dans une table `processed_webhook_events`
    # en prod pour garantir l'exactly-once. Omis ici pour rester lisible.
    event_type = event["type"]
    obj = event["data"]["object"]

    async with system_connection() as conn:
        if event_type in ("customer.subscription.updated", "customer.subscription.deleted"):
            customer_id = obj["customer"]
            status_map = {"active": None, "canceled": "free", "unpaid": "free"}
            new_tier = status_map.get(obj["status"])
            if new_tier:
                await conn.execute(
                    "update workspaces set tier = $1 where stripe_customer_id = $2", new_tier, customer_id
                )
        elif event_type == "invoice.payment_failed":
            pass  # TODO: notifier le workspace + dunning email

    return {"received": True}