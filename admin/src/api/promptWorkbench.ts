import { ApiClient } from './client';
import { readAdminConfig } from '../config/env';
import type { LLMCall } from '../types/prompts';
const client = new ApiClient(readAdminConfig().apiBaseUrl, 255_000);
export interface DebugBody { node_id:string; snapshot_ids:string[]; case_name:string; instruction:string; response_schema:Record<string,unknown>; draft_system?:string }
export interface DebugSide { template_snapshot_id:string; operation_id:string; status:string; calls:LLMCall[] }
export interface DebugCase { test_id:string; node_id:string; case_name:string; created_at:string; input_hash:string; schema_hash:string; sides:DebugSide[] }
export interface DebugResult extends DebugCase { results:(DebugSide & {output?:string;json_valid?:boolean;error_code?:string;model?:string;is_mock?:boolean;validation_notice?:string})[]; notice:string }
export const workbenchApi={
  tests:(node:string,id:string,offset:number,signal?:AbortSignal)=>client.get<{items:DebugCase[];total:number;limit:number;offset:number;notice:string}>(`prompts/${encodeURIComponent(node)}/versions/${encodeURIComponent(id)}/tests?offset=${offset}`,{signal}),
  run:(body:DebugBody,annotation:string,snapshot:string)=>client.post<DebugResult>('prompt-debug',body,{headers:{'X-Admin-Annotation-Token':annotation,'X-Admin-Snapshot-Token':snapshot}}),
};
