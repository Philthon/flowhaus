import type { Row } from "@/lib/api";

/** A field's name as people read it: "company_size" → "Company size". */
export function fieldLabel(name: string): string {
  const text = name.replaceAll("_", " ").trim();
  return text ? text[0].toUpperCase() + text.slice(1) : name;
}

export const isInternal = (name: string) => name.startsWith("_");

/** A field's value as shown: empty shows as a dash. */
export const showValue = (v: unknown) => (v == null || v === "" ? "–" : String(v));

export type FieldKind = "text" | "number" | "yesno";
/**
 * One field of an item being edited: its value as typed, and what kind of value it holds. `blank` is what an empty
 * field from the run was ("" or nothing), so sending it back unedited sends the same value.
 */
export type DraftField = { name: string; value: string; kind: FieldKind; fromRun: boolean; blank?: "" | null };

export function kindOf(v: unknown): FieldKind {
  return typeof v === "number" ? "number" : typeof v === "boolean" ? "yesno" : "text";
}

/** Items as editable fields (internal fields left out), keeping each field's kind. A field that's empty in one item
 * takes its kind from the same field in another item, so typing a number there sends a number. */
export function toDrafts(rows: Row[], max: number): DraftField[][] {
  const some = rows.slice(0, max);
  const kinds = new Map<string, FieldKind>();
  for (const r of some) for (const [name, v] of Object.entries(r)) if (v != null && v !== "" && !kinds.has(name)) kinds.set(name, kindOf(v));
  return some.map((r) =>
    Object.entries(r)
      .filter(([k]) => !isInternal(k))
      .map(([name, v]) =>
        v == null || v === ""
          ? { name, value: "", kind: kinds.get(name) ?? "text", fromRun: true, blank: v === "" ? "" : null }
          : { name, value: String(v), kind: kindOf(v), fromRun: true },
      ),
  );
}

export type Item = Record<string, string | number | boolean | null>;

/**
 * Back to items. A number field must read as a number and a yes/no field as yes or no, so a typo isn't sent as text;
 * a new field takes the kind of the same field in another item, otherwise it's text. Empty means empty.
 * Returns the items, or what to fix ("Lead 2 has two fields called “email”").
 */
export function fromDrafts(drafts: DraftField[][], item: string): { items: Item[] } | { error: string } {
  const known = new Map<string, FieldKind>();
  for (const d of drafts) for (const f of d) if (f.fromRun && f.name.trim()) known.set(f.name.trim(), f.kind);
  const Item = item[0]?.toUpperCase() + item.slice(1);
  const items: Item[] = [];
  for (const [i, d] of drafts.entries()) {
    const out: Item = Object.create(null); // a field may be called "constructor" or "__proto__"
    for (const f of d) {
      const name = f.name.trim();
      if (!name) {
        if (f.value.trim()) return { error: `${Item} ${i + 1}: give the field with “${f.value.trim()}” a name.` };
        continue;
      }
      if (Object.hasOwn(out, name)) return { error: `${Item} ${i + 1} has two fields called “${name}”.` };
      const kind = f.fromRun ? f.kind : (known.get(name) ?? "text");
      const v = f.value.trim();
      if (v === "") out[name] = f.blank ?? null;
      else if (kind === "number") {
        if (Number.isNaN(Number(v))) return { error: `${Item} ${i + 1}: “${fieldLabel(name)}” should be a number.` };
        out[name] = Number(v);
      } else if (kind === "yesno") {
        if (/^(true|yes)$/i.test(v)) out[name] = true;
        else if (/^(false|no)$/i.test(v)) out[name] = false;
        else return { error: `${Item} ${i + 1}: “${fieldLabel(name)}” should be yes or no.` };
      } else out[name] = f.value;
    }
    items.push(out);
  }
  return { items };
}
