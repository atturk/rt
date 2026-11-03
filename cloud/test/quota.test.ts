import { describe, expect, it } from "vitest";
import { quotaUsd } from "../src/quota";
import { testConfig } from "./helpers";

describe("quotaUsd", () => {
  it("3 € con IVA 22%: circa 1,44 USD di uso AI", () => {
    // 300 − 54 IVA − (15 + 50) commissione = 181 cent; ×0,8 ÷1,055 ×1,05
    expect(quotaUsd(300, 54, testConfig)).toBe(1.44);
  });
  it("niente quota se le commissioni mangiano tutto", () => {
    expect(quotaUsd(60, 11, testConfig)).toBe(0);
  });
  it("cresce con l'importo", () => {
    expect(quotaUsd(1000, 180, testConfig)).toBeGreaterThan(quotaUsd(500, 90, testConfig) * 2);
  });
});
