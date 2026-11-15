import { render,screen,waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { expect,it,vi } from 'vitest';
import { ScopeConfirmation } from '../components/ScopeConfirmation';
import { BusinessPlanReview } from '../components/BusinessPlanReview';
import { api } from '../api/client';
import type { Session,ScopePreview } from '../types/contracts';
import fixture from './fixtures/hitl-v1.json';
import { reviewFixture } from './review-fixtures';
const target={field_id:'field_0001',filter_index:0,keyword:'产品经理'};
const preview:ScopePreview={scope:{field_id:target.field_id,keyword:target.keyword,mode:'normalized_contains',values:['产品经理','产品经理（客服）']},matched_row_count:4,dataset_row_count:6,summary:'包含名称变体；已核对完整取值',preview_digest:'a'.repeat(64),dataset_id:'dataset',dataset_version:'version'};
function setup() {
 const session=structuredClone(fixture) as Session;const onSaved=vi.fn();const onPending=vi.fn();
 render(<ScopeConfirmation session={session} target={target} fieldName="岗位名称" busy={false} onSaved={onSaved} onPending={onPending}/>);
 return {session,onSaved,onPending};
}
it('requires actual preview before saving and does not execute or approve',async()=>{
 vi.spyOn(api,'previewScope').mockResolvedValue(preview);const save=vi.spyOn(api,'confirmScope').mockResolvedValue(fixture as Session);const approve=vi.spyOn(api,'approveReal');const execute=vi.spyOn(api,'executeReal');
 const p=setup();expect(screen.getByRole('button',{name:'保存范围并重新审核'})).toBeDisabled();
 await userEvent.click(screen.getByRole('button',{name:'预览匹配范围'}));
 expect(await screen.findByRole('status')).toHaveTextContent('匹配 4 / 6 条');
 await userEvent.click(screen.getByRole('button',{name:'保存范围并重新审核'}));
 await waitFor(()=>expect(save).toHaveBeenCalledWith(p.session,target,'normalized_contains',preview.preview_digest));
 expect(p.onSaved).toHaveBeenCalled();expect(approve).not.toHaveBeenCalled();expect(execute).not.toHaveBeenCalled();
});
it('changing matching mode invalidates the previous preview',async()=>{
 vi.spyOn(api,'previewScope').mockResolvedValue(preview);setup();
 await userEvent.click(screen.getByRole('button',{name:'预览匹配范围'}));await screen.findByRole('status');
 await userEvent.click(screen.getByRole('radio',{name:'仅完全等于“产品经理”'}));
 expect(screen.queryByRole('status')).not.toBeInTheDocument();expect(screen.getByRole('button',{name:'保存范围并重新审核'})).toBeDisabled();
});
it('a failed scope preview cannot create or unlock an approval',async()=>{
 vi.spyOn(api,'previewScope').mockRejectedValue(new Error('范围无法核对'));const save=vi.spyOn(api,'confirmScope');setup();
 await userEvent.click(screen.getByRole('button',{name:'预览匹配范围'}));expect(await screen.findByRole('alert')).toHaveTextContent('范围无法核对');
 expect(save).not.toHaveBeenCalled();expect(screen.getByRole('button',{name:'保存范围并重新审核'})).toBeDisabled();
});
it('shows the scope question returned by the review even when the plan guessed several names',async()=>{
 const session=structuredClone(fixture) as Session;const plan=session.review_plan!;const field=(session.profile && 'fields' in session.profile ?session.profile.fields:[]).find(f=>f.logical_type==='text')!;
 plan.validated_plan.intent_snapshot.constraints.filters=[{raw_text:'华东',validation_status:'unverified'}];
 plan.validated_plan.plan.tasks=[{...plan.validated_plan.plan.tasks[0],steps:[{step_id:'F',operation:'filter',params:{conditions:[{field:field.field_id,operator:'in',value:['华东','华东地区']}]}},...plan.validated_plan.plan.tasks[0].steps.filter(s=>s.operation!=='filter')]}];
 const view=reviewFixture(session,{can_approve:false,scope_questions:[{filter_index:0,keyword:'华东',field_id:field.field_id,field_name:field.display_name}]});
 view.audit.items=[{source:'intent.constraints.filters[0]',raw_text:'华东',status:'unmapped',message:'范围未确认'}];vi.spyOn(api,'review').mockResolvedValue(view);
 render(<BusinessPlanReview session={session} plan={plan} busy={false} onRemove={vi.fn()} onConfirm={vi.fn()} onBasisSaved={vi.fn()}/>);
 expect(await screen.findByRole('region',{name:`${field.display_name}的范围确认`})).toBeVisible();
 expect(screen.getByText(/不必在最初的需求里写死/)).toBeVisible();
 expect(screen.getByRole('button',{name:'确认并开始分析'})).toBeDisabled();
});
it('does not invent a scope question when the review has none',async()=>{
 const session=structuredClone(fixture) as Session;const plan=session.review_plan!;const field=(session.profile && 'fields' in session.profile ?session.profile.fields:[]).find(f=>f.logical_type==='text')!;
 const view=reviewFixture(session,{can_approve:false,scope_questions:[]});vi.spyOn(api,'review').mockResolvedValue(view);
 render(<BusinessPlanReview session={session} plan={plan} busy={false} onRemove={vi.fn()} onConfirm={vi.fn()} onBasisSaved={vi.fn()}/>);
 expect(await screen.findByRole('button',{name:'确认并开始分析'})).toBeDisabled();
 expect(screen.queryByRole('region',{name:`${field.display_name}的范围确认`})).not.toBeInTheDocument();
});
