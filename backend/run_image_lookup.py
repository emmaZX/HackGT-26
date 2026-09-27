"""
Look up images now for every product that doesn't have one (from the backend folder):
    .venv\\Scripts\\python run_image_lookup.py
Free (Open Food Facts + Openverse). Food products take ~7 s each because of Open Food Facts'
rate limit. Products with no match are remembered and skipped next time.
"""

from app.image_lookup import run_image_lookup

print("Looking up images for products without one. Food items take about 7 seconds each...\n")
result = run_image_lookup()
print(f"Looked up:   {result['looked_up']}")
print(f"Found:       {result['found']}")
print(f"No match:    {result['no_match']} (won't be searched again)")
if result["rate_limited"]:
    print("\nStopped early because of a rate limit. Run it again in a few minutes to finish.")
print("\nReload the app to see the images.")
