import golden from '../features/evaluations/golden-set.json';

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

export function GoldenSetPage() {
  return <div className="wf-page">
    <header className="wf-heading"><div>
      <h1>测试数据集</h1>
      <p>需求保真 Golden Set 固定为 5 条。五条共用下面同一份 9 行，页面只展示冻结内容，不启动评测。</p>
    </div></header>
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
  </div>;
}
