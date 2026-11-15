import golden from '../features/evaluations/golden-set.json';

// SHA-256 of the bundled golden-set.json bytes. The content tables render only when the
// dataset API reports the same hash, so a drifted copy is never shown as the current dataset.
export const GOLDEN_BUNDLED_SHA256 = 'fe52a92cc77bb16fa5425f5618c7d7a9dd633f0790eaf341a3c434554a052142';

interface GoldenCase {
  case_id: string; user_input: string; oracle: Record<string, number>;
  error_controls: { code: string; label: string; result: Record<string, number> }[];
  must_execute: string[]; must_forbid: string[]; pass_rule: string; fail_classes: string[];
  non_shanghai_policy?: string;
}
const cases = golden.cases as unknown as GoldenCase[];

function pairs(result: Record<string, number>) {
  return Object.entries(result).map(([city, count]) => `${city} ${count}`).join('、');
}

export function GoldenSetContent() {
  return <>
    <section aria-labelledby="golden-rows">
      <div className="wf-table-top"><strong id="golden-rows">固定 9 行测试数据</strong><span>编号 J01–J09，五条用例不另增行</span></div>
      <div className="wf-table-scroll"><table className="wf-table"><caption className="visually-hidden">固定 9 行测试数据</caption>
        <thead><tr>{golden.columns.map(column => <th key={column}>{column}</th>)}</tr></thead>
        <tbody>{golden.rows.map(row => <tr key={row.编号}>{golden.columns.map(column => <td key={column}>{row[column as keyof typeof row]}</td>)}</tr>)}</tbody>
      </table></div>
    </section>
    <section aria-labelledby="golden-cases">
      <div className="wf-table-top"><strong id="golden-cases">Golden Set</strong><span>{golden.case_count} 条</span></div>
      <div className="wf-table-scroll"><table className="wf-table"><caption className="visually-hidden">需求保真 Golden Set</caption>
        <thead><tr><th>用例</th><th>用户输入</th><th>正确结果</th><th>关键错误对照</th><th>必须执行</th><th>禁止行为</th><th>通过与失败</th></tr></thead>
        <tbody>{cases.map(item => <tr key={item.case_id}>
          <td>{item.case_id}</td>
          <td>{item.user_input}</td>
          <td>{pairs(item.oracle)}{item.non_shanghai_policy ? <p>{item.non_shanghai_policy}</p> : null}</td>
          <td><ul>{item.error_controls.map(control => <li key={control.code + control.label}>{control.label}：{pairs(control.result)}，{control.code}</li>)}</ul></td>
          <td><ul>{item.must_execute.map(text => <li key={text}>{text}</li>)}</ul></td>
          <td><ul>{item.must_forbid.map(text => <li key={text}>{text}</li>)}</ul></td>
          <td><p>{item.pass_rule}</p><p>{item.fail_classes.join('、')}</p></td>
        </tr>)}</tbody>
      </table></div>
    </section>
  </>;
}
