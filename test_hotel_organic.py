import json
import requests
import psycopg2

DB_PARAMS = {
    "dbname": "director_ledger",
    "user": "bjornjasper",
    "password": "1278458kaliko787",  # Authenticated Master Key
    "host": "100.104.14.63",
    "port": 5433
}
ORCHESTRATOR_URL = "http://localhost:42617"

def fetch_and_test():
    print("[*] Connecting to local Postgres ledger on Tailscale port 5433...")
    try:
        conn = psycopg2.connect(**DB_PARAMS)
        cur = conn.cursor()
        
        cur.execute("""
            SELECT shopify_handle, description 
            FROM products 
            WHERE shopify_handle LIKE '%%organic%%' 
            LIMIT 1;
        """)
        row = cur.fetchone()
        
        if row:
            shopify_handle, description = row[0], row[1]
            print(f"[+] Found real ledger data: {shopify_handle}")
        else:
            shopify_handle = "hotel-organic-cold-pressed-argan"
            description = "crystal pure organic cold pressed argan oil with natural sediment layers"
            print("[-] No matching row found in ledger. Simulating high-fidelity Hotel Organic product row...")

        payload = {
            "shopify_handle": shopify_handle,
            "id": "campaign_hotel_organic_01",
            "tailwind_css_theme": {
                "color_scheme": ["#2E4A3F", "#D4AF37"]
            },
            "video_timeline": [
                { "description": f"={description}" }
            ]
        }

        print(f"[*] Firing payload to Autonomous Orchestrator (Port 42617)...")
        response = requests.post(ORCHESTRATOR_URL, json=payload)
        print(f"[+] Response from Orchestrator: {response.status_code}")
        print(json.dumps(response.json(), indent=2))

        cur.close()
        conn.close()

    except Exception as e:
        print(f"[CRITICAL] Operational test error: {str(e)}")

if __name__ == "__main__":
    fetch_and_test()
