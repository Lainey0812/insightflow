import type { ReviewPresentation, Session } from '../types/contracts';
import baseline from './fixtures/review-v2.json';

// A controlled HTTP response, generated from the actual backend mapper.
export function reviewFixture(current: Session, overrides: Partial<ReviewPresentation> = {}): ReviewPresentation {
  return {...structuredClone(baseline) as ReviewPresentation, session_id: current.id, revision: current.revision,
    plan_id: current.review_plan!.plan_id, plan_version: current.review_plan!.plan_version,
    technical_details: {record: current.review_plan}, ...overrides};
}
