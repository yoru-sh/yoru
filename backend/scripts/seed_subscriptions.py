#!/usr/bin/env python3
"""
Script to seed subscription data via API.
Requires admin token from Supabase.
"""

import requests
import json
from typing import Any

API_BASE_URL = "http://localhost:8000/api/v1"

def make_request(method: str, endpoint: str, token: str, data: Any = None) -> dict:
    """Make HTTP request to API."""
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }

    url = f"{API_BASE_URL}{endpoint}"

    try:
        if method == "GET":
            response = requests.get(url, headers=headers)
        elif method == "POST":
            response = requests.post(url, headers=headers, json=data)
        elif method == "PATCH":
            response = requests.patch(url, headers=headers, json=data)
        else:
            raise ValueError(f"Unsupported method: {method}")

        print(f"\n{'='*60}")
        print(f"{method} {endpoint}")
        print(f"Status: {response.status_code}")

        if response.status_code >= 400:
            print(f"Error: {response.text}")
            return None

        result = response.json()
        print(f"Response: {json.dumps(result, indent=2)}")
        return result

    except Exception as e:
        print(f"❌ Error: {e}")
        return None


def seed_features(token: str) -> dict[str, str]:
    """Create test features."""
    print("\n🎯 CREATING FEATURES...")

    features = [
        {
            "key": "ai_analysis",
            "name": "AI Video Analysis",
            "type": "flag",
            "default_value": False,
            "description": "Enable AI-powered video analysis"
        },
        {
            "key": "api_calls",
            "name": "API Calls per Month",
            "type": "quota",
            "default_value": {"limit": 1000, "used": 0},
            "description": "Monthly API call quota"
        },
        {
            "key": "storage_gb",
            "name": "Storage in GB",
            "type": "quota",
            "default_value": {"limit": 10, "used": 0},
            "description": "Storage space in gigabytes"
        },
        {
            "key": "priority_support",
            "name": "Priority Support",
            "type": "flag",
            "default_value": False,
            "description": "Access to priority customer support"
        },
        {
            "key": "custom_branding",
            "name": "Custom Branding",
            "type": "flag",
            "default_value": False,
            "description": "Remove platform branding and add your own"
        }
    ]

    feature_ids = {}

    for feature_data in features:
        result = make_request("POST", "/features/admin/features", token, feature_data)
        if result:
            feature_ids[feature_data["key"]] = result["id"]
            print(f"✅ Created feature: {feature_data['name']} ({result['id']})")

    return feature_ids


def seed_plans(token: str, feature_ids: dict[str, str]) -> dict[str, str]:
    """Create test plans with features."""
    print("\n📋 CREATING PLANS...")

    plans_data = [
        {
            "name": "Free",
            "description": "Perfect for trying out the platform",
            "price": 0.00,
            "billing_period": "monthly",
            "is_active": True,
            "is_custom": False,
            "features": []  # Will add features after creation
        },
        {
            "name": "Starter",
            "description": "For individuals and small teams",
            "price": 9.99,
            "billing_period": "monthly",
            "is_active": True,
            "is_custom": False,
            "features": []
        },
        {
            "name": "Pro",
            "description": "For professional power users",
            "price": 29.99,
            "billing_period": "monthly",
            "is_active": True,
            "is_custom": False,
            "features": []
        },
        {
            "name": "Enterprise",
            "description": "For large organizations with custom needs",
            "price": 99.99,
            "billing_period": "monthly",
            "is_active": True,
            "is_custom": False,
            "features": []
        }
    ]

    plan_ids = {}

    for plan_data in plans_data:
        result = make_request("POST", "/plans/admin/plans", token, plan_data)
        if result:
            plan_ids[plan_data["name"]] = result["id"]
            print(f"✅ Created plan: {plan_data['name']} (${plan_data['price']}/month) - {result['id']}")

    # Attach features to plans
    print("\n🔗 ATTACHING FEATURES TO PLANS...")

    # Free Plan - basic features only
    if "Free" in plan_ids:
        free_features = [
            (feature_ids["api_calls"], {"limit": 100, "used": 0}),
            (feature_ids["storage_gb"], {"limit": 1, "used": 0}),
        ]
        for feature_id, value in free_features:
            make_request(
                "POST",
                f"/plans/admin/plans/{plan_ids['Free']}/features/{feature_id}",
                token,
                {"value": value}
            )

    # Starter Plan
    if "Starter" in plan_ids:
        starter_features = [
            (feature_ids["api_calls"], {"limit": 1000, "used": 0}),
            (feature_ids["storage_gb"], {"limit": 10, "used": 0}),
        ]
        for feature_id, value in starter_features:
            make_request(
                "POST",
                f"/plans/admin/plans/{plan_ids['Starter']}/features/{feature_id}",
                token,
                {"value": value}
            )

    # Pro Plan
    if "Pro" in plan_ids:
        pro_features = [
            (feature_ids["ai_analysis"], True),
            (feature_ids["api_calls"], {"limit": 5000, "used": 0}),
            (feature_ids["storage_gb"], {"limit": 50, "used": 0}),
            (feature_ids["priority_support"], True),
        ]
        for feature_id, value in pro_features:
            make_request(
                "POST",
                f"/plans/admin/plans/{plan_ids['Pro']}/features/{feature_id}",
                token,
                {"value": value}
            )

    # Enterprise Plan
    if "Enterprise" in plan_ids:
        enterprise_features = [
            (feature_ids["ai_analysis"], True),
            (feature_ids["api_calls"], {"limit": 50000, "used": 0}),
            (feature_ids["storage_gb"], {"limit": 500, "used": 0}),
            (feature_ids["priority_support"], True),
            (feature_ids["custom_branding"], True),
        ]
        for feature_id, value in enterprise_features:
            make_request(
                "POST",
                f"/plans/admin/plans/{plan_ids['Enterprise']}/features/{feature_id}",
                token,
                {"value": value}
            )

    return plan_ids


def seed_promo_codes(token: str, plan_ids: dict[str, str]) -> dict[str, str]:
    """Create test promo codes."""
    print("\n🎟️  CREATING PROMO CODES...")

    promo_codes = [
        {
            "code": "LAUNCH50",
            "type": "percentage",
            "value": 50.0,
            "max_uses": 100,
            "expires_at": "2026-12-31T23:59:59Z",
            "is_active": True,
            "conditions": {"description": "Launch promotion - 50% off"}
        },
        {
            "code": "WELCOME10",
            "type": "fixed",
            "value": 10.0,
            "max_uses": None,
            "expires_at": None,
            "is_active": True,
            "conditions": {"description": "Welcome discount - $10 off"}
        }
    ]

    promo_ids = {}

    for promo_data in promo_codes:
        result = make_request("POST", "/promo/admin/promo", token, promo_data)
        if result:
            promo_ids[promo_data["code"]] = result["id"]
            print(f"✅ Created promo: {promo_data['code']} ({promo_data['type']}: {promo_data['value']})")

    return promo_ids


def list_all_data(token: str):
    """List all created data."""
    print("\n📊 LISTING ALL DATA...")

    print("\n--- Features ---")
    make_request("GET", "/features", token)

    print("\n--- Plans ---")
    make_request("GET", "/plans", token)

    print("\n--- Promo Codes (Admin) ---")
    make_request("GET", "/promo/admin/promo", token)


def main():
    """Main seed script."""
    print("🌱 SUBSCRIPTION SYSTEM SEEDER")
    print("="*60)

    # Get admin token
    token = input("\n🔑 Enter your admin Bearer token (from Supabase): ").strip()

    if not token:
        print("❌ Token is required!")
        return

    print("\n🚀 Starting seed process...")

    # Seed features
    feature_ids = seed_features(token)
    if not feature_ids:
        print("❌ Failed to create features. Check your token and API.")
        return

    # Seed plans
    plan_ids = seed_plans(token, feature_ids)
    if not plan_ids:
        print("❌ Failed to create plans.")
        return

    # Seed promo codes
    promo_ids = seed_promo_codes(token, plan_ids)

    # List all data
    list_all_data(token)

    print("\n" + "="*60)
    print("✅ SEEDING COMPLETE!")
    print("="*60)
    print(f"\n📈 Created:")
    print(f"  - {len(feature_ids)} features")
    print(f"  - {len(plan_ids)} plans")
    print(f"  - {len(promo_ids)} promo codes")
    print("\n🌐 Visit http://localhost:8000/api/docs to explore the API")


if __name__ == "__main__":
    main()
