import { createAdminClient } from './client';
const client=createAdminClient();
export interface GoldenCase {case_id:string;user_input:string;oracle:Record<string,number>;error_controls:{code:string;label:string;result:Record<string,number>}[];must_execute:string[];must_forbid:string[];pass_rule:string;fail_classes:string[];non_shanghai_policy?:string}
export interface GoldenDocument {set_id:string;case_count:number;columns:string[];rows:Record<string,string|number|boolean|null>[];cases:GoldenCase[]}
export interface GoldenVersion {version:number;set_id:string;case_count:number;row_count:number;content_hash:string;document:GoldenDocument;created_at:string;created_by:string;change_summary:string;frozen:boolean;source_sha256?:string}
export interface GoldenView {current_version:number;selected:GoldenVersion;versions:Omit<GoldenVersion,'document'>[];notice:string}
export interface GoldenDraft {document:GoldenDocument;base_version:number;revision:number;updated_at:string;updated_by:string}
const headers=(token:string)=>({'X-Admin-Annotation-Token':token});
export const goldenApi={
  versions:(version:string,signal?:AbortSignal)=>client.get<GoldenView>('golden-set'+(version?'?version='+encodeURIComponent(version):''),{signal,cache:'no-store'}),
  draft:(signal?:AbortSignal)=>client.get<GoldenDraft>('golden-set/draft',{signal,cache:'no-store'}),
  save:(body:{document:GoldenDocument;expected_revision:number;annotator:string},token:string)=>client.post<GoldenDraft>('golden-set/draft',body,{headers:headers(token)}),
  publish:(body:{expected_revision:number;base_version:number;annotator:string;change_summary:string},token:string)=>client.post<GoldenVersion>('golden-set/publish',body,{headers:headers(token)}),
};
