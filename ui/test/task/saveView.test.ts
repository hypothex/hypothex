import { expect, test } from "bun:test";
import { stepMetricPanels, viewYaml } from "../../src/task/saveView";

test("viewYaml writes block YAML: plain safe scalars, quoted others, flow lists of scalars", () => {
  const text = viewYaml({
    title: "my view",
    panels: [
      { type: "curves", title: "train", data: { metrics: ["train/loss", "train/acc"], group_by: "group", max_points: 300 } },
      { type: "markdown", title: "Note", text: 'a "quoted" note' },
      { type: "table", title: "yes", data: { fields: [] } },
    ],
  });
  expect(text).toBe(
    [
      'title: "my view"',
      "panels:",
      "  - type: curves",
      "    title: train",
      "    data:",
      "      metrics: [train/loss, train/acc]",
      "      group_by: group",
      "      max_points: 300",
      "  - type: markdown",
      "    title: Note",
      '    text: "a \\"quoted\\" note"',
      "  - type: table",
      '    title: "yes"',
      "    data:",
      "      fields: []",
      "",
    ].join("\n"),
  );
});

test("stepMetricPanels: one curves panel per section with the metrics the search shows", () => {
  const sections = [
    { title: "train", metrics: ["train/loss"] },
    { title: "val", metrics: ["val/loss", "val/top1"] },
  ];
  expect(stepMetricPanels(sections, "")).toEqual([
    { type: "curves", title: "train", data: { metrics: ["train/loss"], group_by: "group" } },
    { type: "curves", title: "val", data: { metrics: ["val/loss", "val/top1"], group_by: "group" } },
  ]);
  expect(stepMetricPanels(sections, "top1")).toEqual([{ type: "curves", title: "val", data: { metrics: ["val/top1"], group_by: "group" } }]);
});
