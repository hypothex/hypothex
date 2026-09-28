import { afterEach, describe, expect, mock, test } from "bun:test";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import {
  ErrorsTable,
  ExampleStrip,
  OutcomeTable,
  SignTestChart,
} from "../../src/pages/components/ExampleCharts";
import {
  binomPmf,
  examplesHeadline,
  examplesMeta,
  exampleTotal,
  pairLabels,
  signTestP,
  stripSegments,
} from "../../src/pages/components/examples";
import { RUN_RF, RUN_SVM, makeDiff, makeRecord } from "./fixtures";

afterEach(cleanup);

describe("sign test", () => {
  test("binomPmf is Binomial(n, 1/2)", () => {
    const pmf = binomPmf(4);
    [1, 4, 6, 4, 1].forEach((c, k) => expect(pmf[k]).toBeCloseTo(c / 16, 12));
    expect(binomPmf(1000).reduce((s, v) => s + v, 0)).toBeCloseTo(1, 9);
    expect(() => binomPmf(-1)).toThrow(RangeError);
  });

  test("signTestP matches exact binomial tails", () => {
    // 2 * P(X <= 3 | n = 12, p = 1/2) = 2 * (1 + 12 + 66 + 220) / 4096 = 598/4096;
    // same as scipy.stats.binomtest(9, 12, 0.5).pvalue = 0.14599609375
    expect(signTestP(9, 3)).toBeCloseTo(598 / 4096, 12);
    expect(signTestP(3, 9)).toBeCloseTo(598 / 4096, 12);
    // 2 * P(X = 0 | n = 10) = 2/1024
    expect(signTestP(10, 0)).toBeCloseTo(2 / 1024, 14);
    // 2 * P(X <= 5 | n = 10) = 2 * 638/1024 > 1, capped
    expect(signTestP(5, 5)).toBe(1);
    expect(signTestP(0, 0)).toBe(1);
    // 400 of 1000: z = (400.5 - 500) / 15.81 = -6.29, normal tail ~3e-10
    const p = signTestP(600, 400);
    expect(p).toBeGreaterThan(1e-11);
    expect(p).toBeLessThan(1e-8);
  });
});

describe("labels and summaries", () => {
  test("stripSegments orders fixed, broken, both wrong, both right", () => {
    const segs = stripSegments(makeDiff());
    expect(segs.map((s) => [s.outcome, s.count, s.label])).toEqual([
      ["fixed", 9, "9 fixed"],
      ["broken", 3, "3 broken"],
      ["both_fail", 11, "11 both wrong"],
      ["both_pass", 157, "157 both right"],
    ]);
    expect(segs[1]?.ids).toEqual(["test-137", "test-167", "test-30"]);
    expect(exampleTotal(makeDiff())).toBe(180);
  });

  test("pairLabels shortens hypotheses and separates equal labels", () => {
    const rf = makeRecord({ run_id: RUN_RF, hypothesis: "baseline rf" });
    expect(pairLabels(rf, makeRecord())).toEqual(["baseline rf", "RBF-kernel SVM"]);
    const rf2 = makeRecord({ run_id: RUN_SVM, hypothesis: "baseline rf" });
    expect(pairLabels(rf, rf2)).toEqual(["baseline rf ef4f", "baseline rf 6f71"]);
  });

  test("headline and meta line", () => {
    expect(examplesHeadline("baseline rf", "RBF-kernel SVM", makeDiff())).toBe(
      "RBF-kernel SVM fixes 9, breaks 3 vs baseline rf, p = 0.15",
    );
    expect(examplesMeta(makeDiff())).toEqual(["n = 180", "net +6", "Δ +0.0333"]);
    const none = { ...makeDiff(), fixed: [], broken: [], both_pass: 0, both_fail: 0 };
    expect(examplesHeadline("A", "B", none)).toBe("B fixes 0, breaks 0 vs A, p = 1.00");
    expect(examplesMeta(none)).toEqual(["n = 0"]);
  });
});

describe("charts", () => {
  test("OutcomeTable is the 2x2 of A and B outcomes", () => {
    const { container } = render(<OutcomeTable labelA="rf" labelB="SVM" diff={makeDiff()} />);
    expect([...container.querySelectorAll("td .n")].map((n) => n.textContent)).toEqual(["157", "3", "9", "11"]);
    expect(screen.getByText("SVM right")).toBeTruthy();
    expect(screen.getByText("rf wrong")).toBeTruthy();
  });

  test("ExampleStrip draws one mark per example with ids as titles", () => {
    const { container } = render(<ExampleStrip diff={makeDiff()} />);
    const count = (cls: string) => container.querySelectorAll(`rect.${cls}`).length;
    expect([count("fixed"), count("broken"), count("both_fail"), count("both_pass")]).toEqual([9, 3, 11, 157]);
    expect(container.querySelector("rect.fixed title")?.textContent).toBe("test-0");
    expect(screen.getByText("157 both right")).toBeTruthy();
  });

  test("ExampleStrip draws one block per outcome above 2000 examples", () => {
    const big = { ...makeDiff(), both_pass: 5000 };
    const { container } = render(<ExampleStrip diff={big} />);
    expect([...container.querySelectorAll("rect")].map((r) => r.getAttribute("class"))).toEqual([
      "fixed",
      "broken",
      "both_fail",
      "both_pass",
    ]);
  });

  test("SignTestChart marks both tails and the observed split", () => {
    const { container } = render(<SignTestChart fixed={9} broken={3} />);
    expect(container.querySelectorAll("rect")).toHaveLength(13);
    // tails as extreme as 9:3 are k <= 3 and k >= 9: 0,1,2,3,9,10,11,12
    expect(container.querySelectorAll("rect[data-tail='true']")).toHaveLength(8);
    expect(screen.getByText("9:3")).toBeTruthy();
    expect(screen.getByText("p = 0.15")).toBeTruthy();
  });

  test("SignTestChart with nothing changed says so", () => {
    render(<SignTestChart fixed={0} broken={0} />);
    expect(screen.getByText("no changed examples")).toBeTruthy();
  });

  test("ErrorsTable marks what A did on B's errors and pages on", () => {
    const onMore = mock(() => {});
    render(
      <ErrorsTable
        rows={[
          { id: "test-7", prediction: 2, reference: 1, scores: {} },
          { id: "test-30", prediction: 2, reference: 0, scores: {} },
        ]}
        total={14}
        labelA="rf"
        labelB="SVM"
        brokenIds={new Set(["test-30"])}
        onMore={onMore}
      />,
    );
    const cells = screen.getAllByRole("cell").map((c) => c.textContent);
    expect(cells).toEqual(["test-7", "2", "1", "wrong", "test-30", "2", "0", "right"]);
    fireEvent.click(screen.getByRole("button", { name: "+12 more" }));
    expect(onMore).toHaveBeenCalledTimes(1);
  });
});
