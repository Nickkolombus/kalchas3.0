export type ExtraCondition = {
  left_scope: string;
  left_metric: string;
  operator: string;
  right_kind: "value" | "metric";
  right_scope: string;
  right_metric: string;
  right_value: number;
  multiplier: number;
  enabled: boolean;
};

export type ConditionCatalog = {
  scopes: { key: string; label: string }[];
  metrics: { key: string; label: string }[];
  operators: string[];
};

const EMPTY: ExtraCondition = {
  left_scope: "triggering",
  left_metric: "npei",
  operator: ">=",
  right_kind: "value",
  right_scope: "opponent",
  right_metric: "corners",
  right_value: 50,
  multiplier: 1,
  enabled: true,
};

function Select({
  value,
  options,
  onChange,
  label,
}: {
  value: string;
  options: { key: string; label: string }[];
  onChange: (value: string) => void;
  label: string;
}) {
  return (
    <label className="admin-cond-field">
      <span>{label}</span>
      <select value={value} onChange={(event) => onChange(event.target.value)}>
        {options.map((option) => (
          <option key={option.key} value={option.key}>
            {option.label}
          </option>
        ))}
      </select>
    </label>
  );
}

export function AdminConditions({
  catalog,
  rows,
  onChange,
}: {
  catalog: ConditionCatalog;
  rows: ExtraCondition[];
  onChange: (rows: ExtraCondition[]) => void;
}) {
  const scopes = catalog.scopes || [];
  const metrics = catalog.metrics || [];
  const operators = (catalog.operators || [">=", ">", "<", "<=", "="]).map((key) => ({
    key,
    label: key,
  }));

  function patch(index: number, fields: Partial<ExtraCondition>) {
    onChange(rows.map((row, i) => (i === index ? { ...row, ...fields } : row)));
  }

  return (
    <aside className="admin-conditions">
      <h2>Extra conditions</h2>
      <p className="admin-hint">
        AND with this strategy&apos;s own Fire gate. Homemade trailing: triggering
        Goals &gt; opponent Goals, or triggering CRN &gt; opponent CRN × 3.
        Favourite and underdog use kickoff odds. Live odds use the cached 1X2
        already on the match - no extra API call.
      </p>
      {rows.length === 0 ? (
        <p className="admin-hint">No extra filter. Native Fire still applies.</p>
      ) : null}
      <ul className="admin-cond-list">
        {rows.map((row, index) => (
          <li key={index} className={row.enabled ? "" : "is-off"}>
            <label className="admin-cond-on">
              <input
                type="checkbox"
                checked={row.enabled}
                onChange={(event) => patch(index, { enabled: event.target.checked })}
              />
              On
            </label>
            <div className="admin-cond-row">
              <Select
                label="Left"
                value={row.left_scope}
                options={scopes}
                onChange={(value) => patch(index, { left_scope: value })}
              />
              <Select
                label="Metric"
                value={row.left_metric}
                options={metrics}
                onChange={(value) => patch(index, { left_metric: value })}
              />
              <Select
                label="Op"
                value={row.operator}
                options={operators}
                onChange={(value) => patch(index, { operator: value })}
              />
            </div>
            <div className="admin-cond-kind">
              <label>
                <input
                  type="radio"
                  name={`kind-${index}`}
                  checked={row.right_kind === "value"}
                  onChange={() => patch(index, { right_kind: "value" })}
                />
                Number
              </label>
              <label>
                <input
                  type="radio"
                  name={`kind-${index}`}
                  checked={row.right_kind === "metric"}
                  onChange={() => patch(index, { right_kind: "metric" })}
                />
                Metric
              </label>
            </div>
            {row.right_kind === "metric" ? (
              <div className="admin-cond-row">
                <Select
                  label="Right"
                  value={row.right_scope}
                  options={scopes}
                  onChange={(value) => patch(index, { right_scope: value })}
                />
                <Select
                  label="Metric"
                  value={row.right_metric}
                  options={metrics}
                  onChange={(value) => patch(index, { right_metric: value })}
                />
                <label className="admin-cond-field">
                  <span>×</span>
                  <input
                    type="number"
                    min={0}
                    step={0.1}
                    value={row.multiplier}
                    onChange={(event) =>
                      patch(index, { multiplier: Number(event.target.value) })
                    }
                  />
                </label>
              </div>
            ) : (
              <label className="admin-cond-field">
                <span>Value</span>
                <input
                  type="number"
                  step="any"
                  value={row.right_value}
                  onChange={(event) =>
                    patch(index, { right_value: Number(event.target.value) })
                  }
                />
              </label>
            )}
            <button type="button" onClick={() => onChange(rows.filter((_, i) => i !== index))}>
              Remove
            </button>
          </li>
        ))}
      </ul>
      <div className="admin-cond-actions">
        <button type="button" onClick={() => onChange([...rows, { ...EMPTY }])}>
          Add condition
        </button>
        {rows.length > 0 ? (
          <button type="button" onClick={() => onChange([])}>
            Clear
          </button>
        ) : null}
      </div>
    </aside>
  );
}
