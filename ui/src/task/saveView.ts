/**
 * "Save as view" (spec 4.2): the Charts tab's shown panels as a view document. The text
 * is block YAML (plain scalars where safe, JSON-quoted otherwise, flow lists of scalars),
 * which the server parses with `yaml.safe_load` and validates like any view.
 */
import type { PanelSpec, ViewSpec } from "../api/models";
import { type MetricSection, matchesSearch } from "./stepMetrics";

const PLAIN = /^[A-Za-z_][A-Za-z0-9_./-]*$/;
const KEYWORD = /^(true|false|null|yes|no|on|off|y|n)$/i;

function scalar(v: unknown): string {
  if (v === null) return "null";
  if (typeof v === "string") return PLAIN.test(v) && !KEYWORD.test(v) ? v : JSON.stringify(v);
  return String(v);
}

const isScalar = (v: unknown): boolean => v === null || typeof v !== "object";

function mapLines(map: Record<string, unknown>, indent: string): string[] {
  const out: string[] = [];
  for (const [key, value] of Object.entries(map)) {
    if (value === undefined) continue;
    if (isScalar(value)) {
      out.push(`${indent}${key}: ${scalar(value)}`);
    } else if (Array.isArray(value)) {
      if (value.every(isScalar)) {
        out.push(`${indent}${key}: [${value.map(scalar).join(", ")}]`);
      } else {
        out.push(`${indent}${key}:`);
        for (const item of value) {
          const inner = mapLines(item as Record<string, unknown>, `${indent}    `);
          if (inner.length === 0) out.push(`${indent}  - {}`);
          else out.push(`${indent}  - ${(inner[0] as string).trimStart()}`, ...inner.slice(1));
        }
      }
    } else {
      const inner = mapLines(value as Record<string, unknown>, `${indent}  `);
      out.push(inner.length ? `${indent}${key}:` : `${indent}${key}: {}`, ...inner);
    }
  }
  return out;
}

/** A view spec as block YAML text (what `PUT .../views/<name>` stores). */
export function viewYaml(spec: ViewSpec): string {
  return `${mapLines(spec as unknown as Record<string, unknown>, "").join("\n")}\n`;
}

/** One curves panel per step-metric section, with the metrics the panel search shows. */
export function stepMetricPanels(sections: readonly MetricSection[], query: string): PanelSpec[] {
  return sections.flatMap((s): PanelSpec[] => {
    const metrics = s.metrics.filter((m) => matchesSearch(m, query));
    return metrics.length ? [{ type: "curves", title: s.title, data: { metrics, group_by: "group" } }] : [];
  });
}
