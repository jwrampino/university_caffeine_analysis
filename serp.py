import os
import json
import time
import getpass
import requests
import pandas as pd
from math import radians, sin, cos, atan2, sqrt
from pathlib import Path

os.environ["SERP_API_KEY"] = getpass.getpass("Enter your SerpAPI key: ")

SERP_OUT = Path("data/caffeine_results.csv")

def haversine_mi(lat1, lon1, lat2, lon2):
    R = 3958.8
    lat1, lon1, lat2, lon2 = map(radians, [lat1, lon1, lat2, lon2])
    dlat, dlon = lat2 - lat1, lon2 - lon1
    a = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
    return R * 2 * atan2(sqrt(a), sqrt(1 - a))

def extract_place(place, uni, page_n):
    coords = place.get("gps_coordinates") or {}
    r_lat = coords.get("latitude")
    r_lon = coords.get("longitude")
    dist = haversine_mi(uni["lat"], uni["lon"], r_lat, r_lon) if r_lat and r_lon else None
    return {
        "university_unitid":  uni["UNITID"],
        "university_name":    uni["institution_name"],
        "source_query":       "coffee",
        "place_id":           place.get("place_id"),
        "data_id":            place.get("data_id"),
        "name":               place.get("title"),
        "type":               place.get("type"),
        "types":              json.dumps(place.get("types", [])),
        "address":            place.get("address"),
        "phone":              place.get("phone"),
        "website":            place.get("website"),
        "rating":             place.get("rating"),
        "reviews":            place.get("reviews"),
        "price":              place.get("price"),
        "open_state":         place.get("open_state"),
        "hours":              json.dumps(place.get("hours", {})),
        "operating_hours":    json.dumps(place.get("operating_hours", {})),
        "service_options":    json.dumps(place.get("service_options", {})),
        "description":        place.get("description"),
        "thumbnail":          place.get("thumbnail"),
        "gps_lat":            r_lat,
        "gps_lon":            r_lon,
        "distance_mi":        round(dist, 4) if dist is not None else None,
        "in_radius":          (dist is not None) and (dist <= uni["assigned_radius"]),
        "page_n":             page_n,
    }

universities = (
    pd.read_csv("data/top_100.csv")
    .dropna(subset=["lat", "lon", "assigned_radius"])
    .pipe(lambda df: df[df["usnews_rank"] <= 50])
)
top_50_ids = set(universities["UNITID"].unique())

if SERP_OUT.exists():
    existing = pd.read_csv(SERP_OUT)
    before = existing.groupby("university_name").size()
    existing = existing[
        (existing["in_radius"] == True) &
        (existing["university_unitid"].isin(top_50_ids))
    ]
    after = existing.groupby("university_name").size()
    dropped = (before - after).loc[lambda x: x > 0]
    if not dropped.empty:
        print("Dropped rows from existing data:")
        for name, n in dropped.items():
            print(f"  {name}: -{n}")
        existing.to_csv(SERP_OUT, index=False)
    print()
else:
    existing = pd.DataFrame()

api_key = os.environ["SERP_API_KEY"]

for _, uni in universities.iterrows():
    uid = uni["UNITID"]
    uni_rows = existing[existing["university_unitid"] == uid] if not existing.empty else pd.DataFrame()
    start_page = int(uni_rows["page_n"].max()) + 1 if not uni_rows.empty else 1

    print(f"{uni['institution_name']} (r={uni['assigned_radius']:.2f} mi) | resuming at page {start_page}")

    for page in range(start_page, start_page + 10):
        try:
            params = {
                "engine":  "google_maps",
                "q":       "coffee",
                "ll":      f"@{uni['lat']},{uni['lon']},14z",
                "type":    "search",
                "start":   page * 20,
                "api_key": api_key,
            }
            r = requests.get("https://serpapi.com/search", params=params, timeout=30)
            r.raise_for_status()
            results = r.json().get("local_results", [])
            if not results:
                print(f"    page {page + 1}: no results, stopping")
                break

            rows = [extract_place(p, uni, page + 1) for p in results]
            new_df = pd.DataFrame(rows)
            in_radius_df = new_df[new_df["in_radius"] == True]

            print(f"    page {page + 1}: {len(results)} fetched | {len(in_radius_df)} in-radius")

            if len(in_radius_df) == 0:
                print(f"    stopping (0 in-radius on page {page + 1})")
                break

            existing = pd.read_csv(SERP_OUT) if SERP_OUT.exists() else pd.DataFrame()
            combined = pd.concat([existing, in_radius_df], ignore_index=True)
            combined = combined.drop_duplicates(subset=["place_id", "university_unitid"], keep="last")
            combined.to_csv(SERP_OUT, index=False)

        except Exception as e:
            print(f"    page {page + 1} error: {e}")
            break

        time.sleep(1)

print(f"\nComplete: {len(pd.read_csv(SERP_OUT))} total rows in {SERP_OUT}")