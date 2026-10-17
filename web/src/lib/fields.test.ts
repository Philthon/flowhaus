import { describe, expect, it } from "vitest";

import { fieldLabel, fromDrafts, toDrafts, type DraftField } from "./fields";

const f = (name: string, value: string, kind: DraftField["kind"] = "text", fromRun = false): DraftField => ({ name, value, kind, fromRun });

describe("field names", () => {
  it("reads like words", () => {
    expect(fieldLabel("company_size")).toBe("Company size");
    expect(fieldLabel("email")).toBe("Email");
  });
});

describe("editing items to test a step", () => {
  it("keeps each field's kind and leaves internal fields out", () => {
    const [item] = toDrafts([{ _row_id: 3, name: "Ana", employees: 40, company: null }], 5);
    expect(item.map((x) => [x.name, x.value, x.kind])).toEqual([
      ["name", "Ana", "text"],
      ["employees", "40", "number"],
      ["company", "", "text"],
    ]);
  });

  it("turns typed text back into numbers, yes/no and empty values", () => {
    const r = fromDrafts([[f("employees", " 250 ", "number", true), f("vip", "yes", "yesno", true), f("note", "", "text", true)]], "lead");
    expect(r).toEqual({ items: [{ employees: 250, vip: true, note: null }] });
  });

  it("gives a new field the kind of the same field in another item", () => {
    const r = fromDrafts([[f("employees", "1", "number", true)], [f("employees", "7")]], "lead");
    expect(r).toEqual({ items: [{ employees: 1 }, { employees: 7 }] });
  });

  it("says what to fix instead of sending a typo", () => {
    expect(fromDrafts([[f("employees", "lots", "number", true)]], "lead")).toEqual({ error: "Lead 1: “Employees” should be a number." });
    expect(fromDrafts([[f("vip", "maybe", "yesno", true)]], "lead")).toEqual({ error: "Lead 1: “Vip” should be yes or no." });
    expect(fromDrafts([[f("email", "a@b.c", "text", true), f("email", "x@y.z")]], "lead")).toEqual({
      error: "Lead 1 has two fields called “email”.",
    });
    expect(fromDrafts([[f("", "orphan")]], "lead")).toEqual({ error: "Lead 1: give the field with “orphan” a name." });
  });

  it("ignores a new field left completely empty", () => {
    expect(fromDrafts([[f("name", "Ana", "text", true), f("", "")]], "lead")).toEqual({ items: [{ name: "Ana" }] });
  });

  it("sends an untouched item back exactly as it came", () => {
    const rows = [{ _row_id: 1, email: "", size: null, name: "Ann" }, { _row_id: 2, email: "b@x.io", size: 40, name: "Bo" }];
    const back = fromDrafts(toDrafts(rows, 5), "lead");
    expect(back).toEqual({ items: [{ email: "", size: null, name: "Ann" }, { email: "b@x.io", size: 40, name: "Bo" }] });
  });

  it("reads a number typed into a field that was empty as a number", () => {
    const drafts = toDrafts([{ size: null }, { size: 40 }], 5);
    drafts[0][0].value = "50";
    expect(fromDrafts(drafts, "lead")).toEqual({ items: [{ size: 50 }, { size: 40 }] });
  });

  it("takes any field name, even ones objects have built in", () => {
    const drafts = toDrafts([{ constructor: "x" }], 5);
    const back = fromDrafts(drafts, "lead");
    expect("items" in back && JSON.parse(JSON.stringify(back.items[0]))).toEqual({ constructor: "x" });
  });
});
