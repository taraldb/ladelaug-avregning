import { describe, expect, it } from "vitest";
import { normalizeDecimalInput } from "./format";

describe("normalizeDecimalInput", () => {
  it.each([
    ["123,45", "123.45"],
    ["123.45", "123.45"],
    ["  42 ", "42"],
    ["1 234,56", "1234.56"],
    ["1 234,56", "1234.56"],
    ["1.234,56", "1234.56"],
    ["1,234.56", "1234.56"],
    ["1,234,567", "1234567"],
    ["-0,01", "-0.01"],
    ["2,5", "2.5"],
    ["", ""],
  ])("normalises %j -> %j", (input, expected) => {
    expect(normalizeDecimalInput(input)).toBe(expected);
  });
});
