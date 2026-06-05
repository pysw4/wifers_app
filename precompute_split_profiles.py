"""Split monolithic predictor5_ap_profiles.json into per-AP files.

Run ONCE locally after re-running precompute_predictor5_profiles.py.
Produces precomputed/profiles_v2/*.json (one per AP) + _index.json.

This replaces the 12 MB monolithic JSON with ~1181 small files (~10 KB each),
so main.py can load only the AP it needs (reducing memory from 62 MB → ~10 KB).
"""
import json, os, hashlib

SRC = "precomputed/predictor5_ap_profiles.json"
DST = "precomputed/profiles_v2"

def main():
    os.makedirs(DST, exist_ok=True)

    with open(SRC) as f:
        data = json.load(f)

    index = []
    for ap_name, profile in data.items():
        name_hash = hashlib.md5(ap_name.encode()).hexdigest()
        with open(os.path.join(DST, f"{name_hash}.json"), "w") as f:
            json.dump({ap_name: profile}, f)
        index.append({"name": ap_name, "hash": name_hash})

    with open(os.path.join(DST, "_index.json"), "w") as f:
        json.dump({"entries": index, "count": len(index)}, f)

    print(f"✅ Split {len(index)} AP profiles into {DST}/ ({os.path.getsize(os.path.join(DST, '_index.json'))/1024:.1f} KB index)")

if __name__ == "__main__":
    main()
