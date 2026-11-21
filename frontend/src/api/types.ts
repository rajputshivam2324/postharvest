// Generated from docs/openapi.json. Run: python3 scripts/generate-api-types.py
export interface AlertOut {
  id: string;
  batch_id: string;
  assessment_id: string;
  severity: string;
  trigger_key: string;
  message: string;
  delivery_status: string;
  acknowledged_at: string | null;
  acknowledged_by: string | null;
  resolved_at: string | null;
  created_at: string;
}
export interface AssessmentOut {
  id: string;
  batch_id: string;
  actor_id: string;
  episode_id: string;
  status: "unknown" | "fresh" | "early_decay" | "spoiling" | "insufficient_data";
  candidate_status: "unknown" | "fresh" | "early_decay" | "spoiling" | "insufficient_data";
  score: number | null;
  features: Record<string, unknown>;
  quality_flags: Array<string>;
  input_references: Record<string, unknown>;
  explanation: string;
  recommendation: string;
  uncertainty: string;
  human_review_required: boolean;
  ai_status: "ok" | "disabled" | "failed" | "invalid_output";
  ai_job_status: string;
  provider: string | null;
  model: string | null;
  rules_version: string;
  policy_snapshot: Record<string, unknown>;
  prompt_version: string;
  workflow_version: string;
  retrieved_evidence_ids: Array<string>;
  cited_evidence_ids: Array<string>;
  ai_explanation: Record<string, unknown> | null;
  created_at: string;
}
export interface AssignmentCreate {
  batch_id: string;
  replace?: boolean;
  note?: string | null;
}
export interface AssignmentOut {
  id: string;
  device_id: string;
  batch_id: string;
  assigned_by: string | null;
  assigned_at: string;
  released_at: string | null;
  released_by: string | null;
  note: string | null;
}
export interface AttemptOut {
  id: string;
  alert_id: string;
  provider: string;
  status: string;
  provider_reference: string | null;
  created_at: string;
}
export interface BaselineCreate {
  gas_adc: number;
  recorded_at: string;
  notes?: string | null;
}
export interface BaselineOut {
  id: string;
  device_id: string;
  actor_id: string;
  gas_adc: number;
  recorded_at: string;
  notes: string | null;
  created_at: string;
}
export interface BatchCreate {
  identifier: string;
  commodity: string;
  quantity: number;
  unit: string;
  storage_location: string;
  notes?: string | null;
  attributes?: Record<string, string | number | number | boolean | null>;
  owner_id?: string | null;
}
export interface BatchOut {
  id: string;
  identifier: string;
  owner_id: string;
  commodity: string;
  quantity: number;
  unit: string;
  storage_location: string;
  notes: string | null;
  attributes: Record<string, unknown>;
  status: "unknown" | "fresh" | "early_decay" | "spoiling" | "insufficient_data";
  archived: boolean;
  created_at: string;
  updated_at: string;
}
export interface BatchUpdate {
  quantity?: number | null;
  unit?: string | null;
  storage_location?: string | null;
  notes?: string | null;
  attributes?: Record<string, string | number | number | boolean | null> | null;
  owner_id?: string | null;
}
export interface ChatRequest {
  message: string;
  batch_id?: string | null;
  history?: Array<ChatTurn>;
}
export interface ChatResponse {
  answer: string;
  mode: "ai" | "summary" | "policy";
  answerable: boolean;
  sources: Array<ChatSource>;
  follow_ups: Array<string>;
  notice?: string | null;
  disclaimer?: string;
}
export interface ChatSource {
  id: string;
  label: string;
  kind: string;
  batch_id?: string | null;
}
export interface ChatTurn {
  role: "user" | "assistant";
  content: string;
}
export interface CredentialOut {
  device_id: string;
  credential: string;
}
export interface DecisionCreate {
  decision_type?: "inspection" | "annotation" | "priority_override";
  rationale: string;
  override_rank?: number | null;
}
export interface DecisionOut {
  id: string;
  batch_id: string | null;
  actor_id: string | null;
  decision_type: string;
  input_references: Record<string, unknown>;
  rationale: string;
  policy_version: string;
  created_at: string;
}
export interface DemoBatchOut {
  batch: BatchOut;
  assessment: AssessmentOut;
  reading_count: number;
  simulated?: boolean;
}
export interface DeviceCreate {
  identifier: string;
  batch_id?: string | null;
  simulated?: boolean;
  firmware_version?: string | null;
}
export interface DeviceOut {
  id: string;
  identifier: string;
  batch_id: string | null;
  active: boolean;
  simulated: boolean;
  last_seen_at: string | null;
  firmware_version: string | null;
  created_at: string;
  paired_at: string | null;
  connection_status: "disabled" | "unpaired" | "never_seen" | "online" | "stale";
}
export interface DevicePairingOut {
  id: string;
  identifier: string;
  batch_id: string | null;
  active: boolean;
  simulated: boolean;
  last_seen_at: string | null;
  firmware_version: string | null;
  created_at: string;
  paired_at: string | null;
  connection_status: "disabled" | "unpaired" | "never_seen" | "online" | "stale";
  pairing_code: string;
  pairing_expires_at: string;
}
export interface DeviceRegistered {
  id: string;
  identifier: string;
  batch_id: string | null;
  active: boolean;
  simulated: boolean;
  last_seen_at: string | null;
  firmware_version: string | null;
  created_at: string;
  paired_at: string | null;
  connection_status: "disabled" | "unpaired" | "never_seen" | "online" | "stale";
  credential: string;
}
export interface DeviceUpdate {
  active: boolean;
}
export interface EvidenceItem {
  id: string;
  source_type: string;
  text: string;
}
export interface GuidanceCreate {
  identifier: string;
  commodity: string;
  text: string;
  source_url: string;
  review_note: string;
}
export interface HTTPValidationError {
  detail?: Array<ValidationError>;
}
export interface IngestionOut {
  reading: ReadingOut;
  duplicate: boolean;
  notice?: string | null;
}
export interface LoginInput {
  user_id: string;
  password: string;
}
export interface LoginOut {
  access_token: string;
  token_type?: string;
  expires_in: number;
  expires_at: string;
  user: UserOut;
}
export interface ObservationCreate {
  observation_type?: "routine" | "start_condition" | "final_outcome" | "correction";
  observed_at: string;
  condition: string;
  firmness?: string | null;
  visible_mould?: boolean | null;
  weight_kg?: number | null;
  notes?: string | null;
  photo_reference?: string | null;
  corrects_id?: string | null;
}
export interface ObservationOut {
  id: string;
  batch_id: string;
  observer_id: string;
  observation_type: string;
  observed_at: string;
  condition: string;
  firmness: string | null;
  visible_mould: boolean | null;
  weight_kg: number | null;
  notes: string | null;
  photo_reference: string | null;
  corrects_id: string | null;
  created_at: string;
}
export interface Page_AlertOut_ {
  items: Array<AlertOut>;
  total: number;
  limit: number;
  offset: number;
}
export interface Page_AssessmentOut_ {
  items: Array<AssessmentOut>;
  total: number;
  limit: number;
  offset: number;
}
export interface Page_AssignmentOut_ {
  items: Array<AssignmentOut>;
  total: number;
  limit: number;
  offset: number;
}
export interface Page_AttemptOut_ {
  items: Array<AttemptOut>;
  total: number;
  limit: number;
  offset: number;
}
export interface Page_BaselineOut_ {
  items: Array<BaselineOut>;
  total: number;
  limit: number;
  offset: number;
}
export interface Page_BatchOut_ {
  items: Array<BatchOut>;
  total: number;
  limit: number;
  offset: number;
}
export interface Page_DecisionOut_ {
  items: Array<DecisionOut>;
  total: number;
  limit: number;
  offset: number;
}
export interface Page_DeviceOut_ {
  items: Array<DeviceOut>;
  total: number;
  limit: number;
  offset: number;
}
export interface Page_ObservationOut_ {
  items: Array<ObservationOut>;
  total: number;
  limit: number;
  offset: number;
}
export interface Page_ReadingOut_ {
  items: Array<ReadingOut>;
  total: number;
  limit: number;
  offset: number;
}
export interface Page_UserOut_ {
  items: Array<UserOut>;
  total: number;
  limit: number;
  offset: number;
}
export interface Page_VendorOut_ {
  items: Array<VendorOut>;
  total: number;
  limit: number;
  offset: number;
}
export interface PairingClaim {
  code: string;
}
export interface PairingClaimed {
  device_id: string;
  identifier: string;
  credential: string;
  simulated: boolean;
  sampling_seconds: number;
}
export interface PairingOut {
  device_id: string;
  pairing_code: string;
  expires_at: string;
}
export interface PriorityItem {
  batch_id: string;
  identifier: string;
  rank: number;
  computed_rank?: number;
  override_rank?: number | null;
  override_rationale?: string | null;
  override_record_id?: string | null;
  score: number;
  status: "unknown" | "fresh" | "early_decay" | "spoiling" | "insufficient_data";
  factors: Record<string, number>;
  simulated: boolean;
  assessment_id: string | null;
  advisory?: string;
}
export interface PriorityOut {
  items: Array<PriorityItem>;
  total: number;
  limit: number;
  offset: number;
  ranking_meaningful: boolean;
  policy_version?: string;
}
export interface ReadingCreate {
  device_id: string;
  batch_id?: string | null;
  event_id?: string | null;
  temperature_c: number;
  humidity_pct: number;
  gas_adc: number;
  gas_voltage_v: number;
  warming_up?: boolean;
  simulated?: boolean;
  firmware_version?: string | null;
  source_timestamp: string;
}
export interface ReadingOut {
  id: string;
  device_id: string;
  batch_id: string | null;
  event_id: string | null;
  temperature_c: number;
  humidity_pct: number;
  gas_adc: number;
  gas_voltage_v: number;
  warming_up: boolean;
  simulated: boolean;
  firmware_version: string | null;
  source_timestamp: string;
  ingested_at: string;
}
export interface SignupInput {
  user_id: string;
  password: string;
  role?: "operator" | "vendor";
}
export interface UserCreate {
  user_id: string;
  password: string;
  role?: "admin" | "operator" | "vendor";
}
export interface UserOut {
  id: string;
  user_id: string;
  role: "admin" | "operator" | "vendor";
  active: boolean;
  created_at: string;
}
export interface UserUpdate {
  active: boolean;
}
export interface ValidationError {
  loc: Array<string | number>;
  msg: string;
  type: string;
  input?: unknown;
  ctx?: Record<string, unknown>;
}
export interface VendorOut {
  id: string;
  user_id: string;
}
