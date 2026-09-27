/**
 * Picks a category illustration from /public/illustrations for products without a photo.
 * Matched by keyword against the product's category, name and brand (categories are free text).
 * First match wins, so more specific groups come first.
 */
const RULES: [string, RegExp][] = [
  ["battery", /batter|charger|power ?bank|e-?bike|scooter|lithium|usb/i],
  ["heater", /heater|electric|outlet|extension cord|space heat|fan\b|lamp|light/i],
  ["baby", /baby|infant|toddler|child|kid|toy|crib|stroller|pacifier|wipes/i],
  ["kitchen", /kitchen|cooker|blender|kettle|fryer|toaster|oven|appliance|pot\b|pan\b/i],
  ["personal-care", /personal care|cosmetic|lotion|shampoo|skin|sunscreen|razor|hair|drug|medic|supplement/i],
  ["food", /food|lettuce|romaine|salad|melon|cantaloupe|chicken|meat|cheese|milk|snack|sprout|powder|produce/i],
  ["home", /furniture|dresser|chair|sofa|mattress|bed\b|home|decor|rug|shelf/i],
];

export function illustrationFor(p: { category?: string | null; name: string; brand?: string | null }) {
  const text = `${p.category || ""} ${p.name} ${p.brand || ""}`;
  const hit = RULES.find(([, re]) => re.test(text));
  return `/illustrations/${hit ? hit[0] : "generic"}.svg`;
}
