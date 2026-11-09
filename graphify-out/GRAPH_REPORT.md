# Graph Report - llm-genai  (2026-11-09)

## Corpus Check
- 298 files · ~143,659 words
- Verdict: corpus is large enough that graph structure adds value.
- Unclassified: 29 file(s) not represented in the graph (top: .bat 17, (none) 7, .example 1)

## Summary
- 3353 nodes · 10538 edges · 148 communities (113 shown, 35 thin omitted)
- Extraction: 91% EXTRACTED · 9% INFERRED · 0% AMBIGUOUS · INFERRED: 942 edges (avg confidence: 0.91)
- Token cost: 492,311 input · 0 output

## Community Hubs (Navigation)
- Model & Project Services
- Chat/Image Service Context
- Rate Limit & Quota
- Admin Catalog CRUD
- Settings & Database Core
- Provider Base & Registry
- SSE Streaming
- Router Service & Fallback
- OpenVINO LLM Backend
- Usage Accounting
- Public API Controllers
- Device Manager
- Admin Keys & Schemas
- Runtime App State
- Chat Completion Controller
- Fake GenAI Test Double
- Unified Schema & Translation
- Provider Adapter Tests
- Traefik Dynamic Config
- ORM Models Base
- Tool Call Parsers
- Gemini/Anthropic Message Mapping
- Admin Projects & Observe
- Retention Maintenance
- Model Catalog Registry
- Logger & Redaction
- Model Download & Measure Scripts
- Traefik Static Config
- manage.py CLI
- Metrics & Runtime Health
- OpenAI Provider
- PRD Concepts
- Console Env Status
- OpenVINO Common Loading
- Tasks: Local Runtime & DB
- Image Controller
- Provider Billing
- OpenRouter Free Models
- Hardware E2E Tests
- Admin Console JS
- Image Input Handling
- API Key Service
- Local Runtime Provider
- OV LLM Tests
- Device Manager Tests
- OpenVINO Model Conversion
- Tasks: Routing & QA
- API v1 Integration Tests
- Framework Examples & Backup
- Tasks: Setup & Core
- Profile: full
- Tasks: Usage & API v1
- Seed Models: Models
- Error Handling Tests
- OV Diffusion Backend
- Backend Threading Helpers
- Profile: ram16
- Test Config & Live Providers
- OV Diffusion Tests
- OpenAI SDK Examples
- Profile: remote-only
- Load Tests & Port Wait
- Admin Integration Tests
- Auth Integration Tests
- Hardware LLM Tests
- SD NPU Tests & Artifacts
- Task List & Milestones
- Seed Models: Local Params
- DB Model Tests
- Tasks: Errors & Providers
- Tasks: Deployment & Health
- Model Memory Measurement
- App Factory & Test Setup
- OpenAI Provider Tests
- Admin Query Pagination
- Inference Service
- Helper Utilities
- Request Converters
- API Key Crypto
- Local Backend Interface
- Request Context Middleware
- Client Integration Docs
- Runtime Event Service
- Local Benchmarks
- Alembic Migrations
- Error Handler Middleware
- Config Validation Tests
- Admin Usage Verification
- Profile Integration Tests
- Health Ready Tests
- Body Size Limit
- Release & DB Decisions
- NPU & FIM Model Notes
- Deployment Mode A & Device Budget
- Local Smoke Script
- Health Service
- Seed Models: Providers
- Client & Proxy Docs
- OV VLM Backend
- Runtime Security & Entry
- Secret Scan Script
- Admin Requests Routes
- Admin Runtime Routes
- Console Route
- Migrations Env
- JS SDK Example
- Provider Test Fixtures
- Usage Endpoint
- Tasks: Admin API & Audit
- Custom Provider Tests
- Hermes Tool Prompt
- Seed Models: Routes
- Admin Console Feature
- Admin Audit Routes
- Admin Quota Routes
- Runtime Launcher
- Auth Test Fixtures
- SD1.5 img2img Smoke
- Admin Maintenance Routes
- SD1.5 txt2img Smoke
- Vision Smoke Input
- SD Component Devices
- OpenVINO-only Decision
- Console Kit
- Usage Charts
- Test Layers & Quality Gate
- Stub: Release v1 acceptance criteria
- Stub: scripts/probe_devices.py
- Stub: llm_gateway

## God Nodes (most connected - your core abstractions)
1. `SessionLocal()` - 134 edges
2. `AuthContext` - 119 edges
3. `Request` - 115 edges
4. `ModelConfig` - 108 edges
5. `get_settings()` - 80 edges
6. `InvalidRequestError` - 71 edges
7. `GatewayError` - 60 edges
8. `RequestCtx` - 56 edges
9. `LocalModelSpec` - 55 edges
10. `Router` - 54 edges

## Surprising Connections (you probably didn't know these)
- `body()` --indirect_call--> `gen()`  [INFERRED]
  app/controllers/common.py → tests/unit/test_errors.py
- `_database_url()` --uses--> `ConfigError`  [INFERRED]
  migrations/env.py → app/core/config.py
- `main()` --uses--> `ConfigError`  [INFERRED]
  scripts/manage.py → app/core/config.py
- `main()` --uses--> `ConfigError`  [INFERRED]
  scripts/run_runtime.py → app/core/config.py
- `main()` --uses--> `ConfigError`  [INFERRED]
  scripts/run_server.py → app/core/config.py

## Import Cycles
- None detected.

## Hyperedges (group relationships)
- **Request recording & usage accounting pipeline** — docs_database_requests, docs_database_request_attempts, docs_database_usage_daily, docs_operations_usage_fallback_replay, docs_operations_orphan_sweeper, docs_database_usage_consistency_check [INFERRED 0.85]
- **Local models constrained by shared UMA GPU/NPU memory** — docs_hardware_uma_memory_budget, docs_model_catalog_qwen2_5_7b, docs_model_catalog_qwen2_5_coder_7b, docs_model_catalog_qwen2_5_coder_1_5b, docs_model_catalog_qwen2_vl_2b, docs_model_catalog_sd_1_5, docs_model_catalog_operational_profiles [INFERRED 0.85]
- **Mode B network exposure security controls** — docs_deployment_mode_b_traefik, docs_deployment_behind_proxy, docs_deployment_tls_self_signed, docs_client_integration_coding_assistants [INFERRED 0.75]
- **Free OpenRouter models with no public standard endpoint or listed price** — docs_openrouter_dots_studio_free_dots_3_note_preview, docs_openrouter_north_mini_code_free_north_mini_code, docs_openrouter_nvidia_free_nemotron_3_nano_omni_30b_a3b_reasoning, docs_openrouter_recursive_free_flint_v1_0, docs_openrouter_xingchen_free_xing4_0_29b_a4b [EXTRACTED 1.00]
- **NVIDIA Nemotron free model family on OpenRouter** — docs_openrouter_nvidia_free_nemotron_3_ultra_550b_a55b, docs_openrouter_nvidia_free_nemotron_3_5_super_vl, docs_openrouter_nvidia_free_nemotron_3_5_lightning, docs_openrouter_nvidia_free_nemotron_3_nano_omni_30b_a3b_reasoning, docs_openrouter_nvidia_free_nemotron_3_5_content_safety [EXTRACTED 1.00]
- **OpenRouter request lifecycle: auth, chat completions, streaming, errors** — openrouter_bearer_api_key_auth, openrouter_chat_completions_api, openrouter_sse_streaming, openrouter_error_codes [INFERRED 0.85]
- **Mandatory local models (Qwen2.5-7B, SD v1.5, Qwen2.5-Coder 7B/1.5B, Qwen2-VL-2B)** — llm_gateway_docs_v2_docs_prd_qwen2_5_7b, llm_gateway_docs_v2_docs_prd_sd_1_5, llm_gateway_docs_v2_docs_prd_qwen2_5_coder_7b, llm_gateway_docs_v2_docs_prd_qwen2_5_coder_1_5b, llm_gateway_docs_v2_docs_prd_qwen2_vl_2b [EXTRACTED 1.00]
- **Device memory management (budget, pinning, eviction, event logging, no-CPU)** — llm_gateway_docs_v2_docs_prd_device_manager, llm_gateway_docs_v2_docs_prd_pinned_model, llm_gateway_docs_v2_docs_prd_runtime_events, llm_gateway_docs_v2_docs_prd_no_cpu_inference, llm_gateway_docs_v2_docs_prd_models_table [EXTRACTED 1.00]
- **M3 Local Runtime milestone tasks** — llm_gateway_docs_v2_tasks_task_09_hardware_model_acquisition, llm_gateway_docs_v2_tasks_task_10_local_runtime_device_manager, llm_gateway_docs_v2_tasks_task_11_runtime_backend_openvino_llm, llm_gateway_docs_v2_tasks_task_12_runtime_backend_openvino [EXTRACTED 1.00]
- **Provider adapters implementing BaseProvider contract** — llm_gateway_docs_v2_tasks_task_06_provider_base_registry_streaming_baseprovider, llm_gateway_docs_v2_tasks_task_07_provider_openai_openaiprovider, llm_gateway_docs_v2_tasks_task_08_provider_anthropic_gemini_anthropicprovider, llm_gateway_docs_v2_tasks_task_08_provider_anthropic_gemini_geminiprovider, llm_gateway_docs_v2_tasks_task_10_local_runtime_device_manager_localruntimeprovider [INFERRED 0.95]
- **OpenVINO runtime backends implementing LocalBackend** — llm_gateway_docs_v2_tasks_task_10_local_runtime_device_manager_localbackend, llm_gateway_docs_v2_tasks_task_11_runtime_backend_openvino_llm_ov_llm_backend, llm_gateway_docs_v2_tasks_task_11_runtime_backend_openvino_llm_ov_vlm_backend, llm_gateway_docs_v2_tasks_task_12_runtime_backend_openvino_ov_diffusion_backend [INFERRED 0.95]
- **Local model acquisition & catalog sync pipeline** — llm_gateway_docs_v2_tasks_task_09_hardware_model_acquisition_probe_devices, llm_gateway_docs_v2_tasks_task_09_hardware_model_acquisition_download_models, llm_gateway_docs_v2_tasks_task_09_hardware_model_acquisition_convert_openvino, llm_gateway_docs_v2_tasks_task_09_hardware_model_acquisition_measure_models, llm_gateway_docs_v2_tasks_task_04_database_models_migrations_seed_models_yaml, llm_gateway_docs_v2_tasks_task_04_database_models_migrations_manage_seed [EXTRACTED 1.00]
- **Request admission and execution pipeline (rate limit -> quota -> resolve -> usage.start -> execute -> usage.finish)** — llm_gateway_docs_v2_tasks_task_14_public_api_v1_chat_controller, llm_gateway_docs_v2_tasks_task_16_ratelimit_quota_ratelimit_service, llm_gateway_docs_v2_tasks_task_16_ratelimit_quota_quota_service, llm_gateway_docs_v2_tasks_task_13_routing_fallback_router_service, llm_gateway_docs_v2_tasks_task_15_usage_accounting_usage_service, llm_gateway_docs_v2_tasks_task_13_routing_fallback_chat_service [EXTRACTED 1.00]
- **NF9 no-CPU-inference enforcement across accounting, metrics, admin and tests** — llm_gateway_docs_v2_tasks_task_15_usage_accounting_device_accountability, llm_gateway_docs_v2_tasks_task_18_health_metrics_cpu_device_alarm, llm_gateway_docs_v2_tasks_task_17_admin_api_audit_pinned_vram_budget, llm_gateway_docs_v2_tasks_task_20_testing_qa_hardware_tests [INFERRED 0.85]
- **Traefik edge protection (allowlist, rate limit, no runtime route)** — llm_gateway_docs_v2_tasks_task_22_deployment_with_traefik_traefik, llm_gateway_docs_v2_tasks_task_22_deployment_with_traefik_admin_allowlist, llm_gateway_docs_v2_tasks_task_22_deployment_with_traefik_global_ratelimit, llm_gateway_docs_v2_tasks_task_22_deployment_with_traefik_dynamic_yml [EXTRACTED 1.00]

## Communities (148 total, 35 thin omitted)

### Community 0 - "Model & Project Services"
Cohesion: 0.06
Nodes (75): valid_provider_key_env(), ProjectAllowedModel, ApiKeyCreatedOut, ApiKeyOut, ModelOut, _Out, ProjectOut, ProviderOut (+67 more)

### Community 1 - "Chat/Image Service Context"
Cohesion: 0.07
Nodes (26): ModelConfig, UnifiedChatRequest, UnifiedChunk, absorb_chunk(), ChatService, clamp_max_tokens(), stream_with_fallback(), _clamp() (+18 more)

### Community 2 - "Rate Limit & Quota"
Cohesion: 0.06
Nodes (28): period_start(), QuotaRule, QuotaService, seconds_to_reset(), Totals, _UsageEntry, _Bucket, Decision (+20 more)

### Community 3 - "Admin Catalog CRUD"
Cohesion: 0.06
Nodes (41): create_model(), create_provider(), create_route(), delete_model(), delete_provider(), delete_route(), get_catalog(), list_models() (+33 more)

### Community 4 - "Settings & Database Core"
Cohesion: 0.07
Nodes (17): Settings, configure_db(), create_engine(), dispose_db(), get_engine(), init_db(), ping_db(), _cleanup_ratelimit_forever() (+9 more)

### Community 5 - "Provider Base & Registry"
Cohesion: 0.08
Nodes (13): ProviderHealth, UnifiedChatResponse, UnifiedEmbeddingResponse, AnthropicProvider, _message(), BaseProvider, GeminiProvider, CapabilityNotSupported (+5 more)

### Community 6 - "SSE Streaming"
Cohesion: 0.07
Nodes (39): _has_payload(), body(), event(), aiter_sse(), _DisconnectAware, drain_finishers(), guarded_stream(), parse_sse_lines() (+31 more)

### Community 7 - "Router Service & Fallback"
Cohesion: 0.10
Nodes (40): RouteConfig, RouteTarget, _all_failed(), AllCandidatesFailed, _allowed(), Capabilities, CircuitBreaker, Router (+32 more)

### Community 8 - "OpenVINO LLM Backend"
Cohesion: 0.09
Nodes (11): ContextLengthExceeded, OVLLMBackend, chunk(), events_to_chunks(), on_text(), put(), work(), write() (+3 more)

### Community 9 - "Usage Accounting"
Cohesion: 0.08
Nodes (21): _clip(), _looks_base64(), strip_images(), _upsert_daily(), UsageService, _on_finish(), _utc_day(), write_record() (+13 more)

### Community 10 - "Public API Controllers"
Cohesion: 0.12
Nodes (14): payload_body(), completions(), embeddings(), AuthContext, ChatCompletionRequest, CompletionRequest, EmbeddingRequest, OpenAIRequest (+6 more)

### Community 11 - "Device Manager"
Cohesion: 0.07
Nodes (10): DeviceOOM, ModelBusy, LocalModelSpec, DeviceManager, DeviceStatus, EventRecorder, LoadedModel, _NullRecorder (+2 more)

### Community 12 - "Admin Keys & Schemas"
Cohesion: 0.08
Nodes (29): create_key(), list_keys(), revoke_key(), rotate_key(), set_key_allowed_models(), archive_project(), create_project(), get_project() (+21 more)

### Community 13 - "Runtime App State"
Cohesion: 0.08
Nodes (32): RuntimeCatalog, build_state(), check_devices(), RuntimeStartError, detect(), DeviceInfo, DeviceProbe, _probe_openvino() (+24 more)

### Community 14 - "Chat Completion Controller"
Cohesion: 0.06
Nodes (21): create_chat_completion(), estimate_request_tokens(), finish_error(), get_router(), open_sse(), create_completion(), create_embeddings(), _allowed() (+13 more)

### Community 15 - "Fake GenAI Test Double"
Cohesion: 0.06
Nodes (18): ChatHistory, CppStdGenerator, _encode_ids(), FinishReason, GenerationConfig, Image2ImagePipeline, _ImagePipeline, LLMPipeline (+10 more)

### Community 16 - "Unified Schema & Translation"
Cohesion: 0.09
Nodes (22): FunctionCall, FunctionDef, _Model, RuntimeMeta, ToolCall, ToolCallDelta, ToolDef, UnifiedCompletionRequest (+14 more)

### Community 17 - "Provider Adapter Tests"
Cohesion: 0.10
Nodes (34): model_cfg(), provider_cfg(), sse_body(), sse_response(), multi_turn_request(), _collect_tool_calls(), _provider(), _req() (+26 more)

### Community 18 - "Traefik Dynamic Config"
Cohesion: 0.04
Nodes (46): ipAllowList, buffering, maxRequestBodyBytes, memRequestBodyBytes, Server, entryPoints, rule, service (+38 more)

### Community 19 - "ORM Models Base"
Cohesion: 0.19
Nodes (16): Base, check_in(), CreatedAtMixin, TimestampMixin, uuid_pk(), GeneratedImage, Model, Project (+8 more)

### Community 20 - "Tool Call Parsers"
Cohesion: 0.10
Nodes (23): _could_be_lenient_call(), parse_hermes(), parse_lenient(), parse_tool_output(), ParsedOutput, _partial_suffix(), StreamToolParser, _to_openai() (+15 more)

### Community 21 - "Gemini/Anthropic Message Mapping"
Cohesion: 0.11
Nodes (26): ImagePart, TextPart, UnifiedMessage, build_messages(), _content_blocks(), _simplify(), _to_blocks(), dumps_arguments() (+18 more)

### Community 22 - "Admin Projects & Observe"
Cohesion: 0.15
Nodes (27): actor(), audit_logs(), cache_reload(), get_request(), provider_billing(), runtime_events(), runtime_load(), runtime_unload() (+19 more)

### Community 23 - "Retention Maintenance"
Cohesion: 0.12
Nodes (13): get_settings(), RequestPayload, MaintenanceService, seconds_until_daily_run(), utcnow(), _bulk_requests(), _count(), test_daily_schedule_0030_utc() (+5 more)

### Community 24 - "Model Catalog Registry"
Cohesion: 0.09
Nodes (15): adapter_of(), keyless(), load_registry(), ModelCatalog, ProviderRegistry, ProviderConfig, test_load_providers_models_routes(), test_reload_reflects_db_changes_without_restart() (+7 more)

### Community 25 - "Logger & Redaction"
Cohesion: 0.09
Nodes (19): _attach(), _console_formatter(), _file_handler(), _InProcessQueueHandler, _is_sensitive_key(), _json_formatter(), redact_processor(), redact_value() (+11 more)

### Community 26 - "Model Download & Measure Scripts"
Cohesion: 0.12
Nodes (18): main(), plan(), main(), pipeline_properties(), _prompt_of(), round_vram(), validate_budget(), load_seed() (+10 more)

### Community 27 - "Traefik Static Config"
Cohesion: 0.05
Nodes (36): accessLog, bufferingSize, fields, filePath, format, api, dashboard, address (+28 more)

### Community 28 - "manage.py CLI"
Cohesion: 0.14
Nodes (25): AuditLog, clear_ov_cache(), _apply_profile(), _audit_change(), build_parser(), cmd_allow_models(), cmd_apply_profile(), cmd_clear_ov_cache() (+17 more)

### Community 29 - "Metrics & Runtime Health"
Cohesion: 0.10
Nodes (12): request_started(), health_ready(), load_model(), metrics(), reload_catalog(), shutdown(), _state(), status() (+4 more)

### Community 30 - "OpenAI Provider"
Cohesion: 0.15
Nodes (4): drop_none(), OpenAIProvider, parse_usage(), _upstream_message()

### Community 31 - "PRD Concepts"
Cohesion: 0.08
Nodes (30): PRD - LLM Gateway v2.0, Additional llama.cpp models (Llama-3.2-3B, Llama-3.1-8B, Phi-3.5-mini, DeepSeek-R1-Distill-Qwen-7B, nomic-embed), Admin API & runtime admin endpoints, API key auth (lgw_ prefix, HMAC-SHA256 with pepper, scopes), bge-m3 OpenVINO embedding (NPU, pinned), PostgreSQL schema (projects, api_keys, providers, models, requests, usage_daily, audit_logs), Deployment modes (without/with Traefik), FIM (Fill-in-the-Middle) autocomplete (+22 more)

### Community 32 - "Console Env Status"
Cohesion: 0.10
Nodes (16): _dotenv(), env_status(), env_vars(), provider_key_states(), _secret(), secret_state(), _var(), _client() (+8 more)

### Community 33 - "OpenVINO Common Loading"
Cohesion: 0.13
Nodes (10): ModelLoadFailed, cache_dir(), cache_entries(), cancel_bridge(), device_kind(), genai(), model_path(), resolve_path() (+2 more)

### Community 34 - "Tasks: Local Runtime & DB"
Cohesion: 0.08
Nodes (31): Alembic migrations (0001_initial), CHECK constraint ck_local_has_backend, scripts/manage.py seed (--update-local), ORM models (app/models/*: Project, ApiKey, Model, Request, GeneratedImage, RuntimeEvent...), scripts/seed_models.yaml (local model catalog & routes), manage.py CLI (create-admin-key, create-project, create-key), Multi-turn tool-calling contract test, scripts/convert_openvino.py (optimum-cli wrapper) (+23 more)

### Community 35 - "Image Controller"
Cohesion: 0.12
Nodes (13): admit_and_start(), public_base(), create_image(), edit_image(), get_image_file(), _payload_meta(), _run(), image_file() (+5 more)

### Community 36 - "Provider Billing"
Cohesion: 0.14
Nodes (17): BillingError, _error_message(), _failed(), fetch_anthropic(), fetch_openai(), _get_pages(), provider_billing(), _range() (+9 more)

### Community 37 - "OpenRouter Free Models"
Cohesion: 0.16
Nodes (31): OpenRouter Dots Studio Free Model Guide, Dots Studio: Dots3-Note Preview (free) (dots-studio/dots-3-note-preview), OpenRouter Google Gemma Free Models Guide, Google: Gemma 4 26B A4B (free) (google/gemma-4-26b-a4b-it), Google: Gemma 4 31B (free) (google/gemma-4-31b-it), OpenRouter LiquidAI Free Model Guide, LiquidAI: LFM2.5-2.6B (free) (liquid/lfm-2.5-2.6b), OpenRouter Cohere North Mini Code Free Model Guide (+23 more)

### Community 38 - "Hardware E2E Tests"
Cohesion: 0.12
Nodes (19): active(), call_model(), call_retry_busy(), gw(), metric_sum(), metrics(), png_data_url(), require() (+11 more)

### Community 39 - "Admin Console JS"
Cohesion: 0.15
Nodes (29): actualSection(), archiveProject(), boot(), catalogItems(), createKey(), createProject(), editKeyModels(), editModels() (+21 more)

### Community 40 - "Image Input Handling"
Cohesion: 0.12
Nodes (15): limited_receive(), PayloadTooLarge, _check_host(), _decode_data_url(), decode_image(), fetch_url(), _is_public(), load_image() (+7 more)

### Community 41 - "API Key Service"
Cohesion: 0.14
Nodes (6): ApiKey, _CachedKey, KeyService, AuthenticationError, ProjectSuspended, test_client_key_requires_project()

### Community 42 - "Local Runtime Provider"
Cohesion: 0.14
Nodes (3): _json(), LocalRuntimeProvider, parse_runtime_meta()

### Community 43 - "OV LLM Tests"
Cohesion: 0.17
Nodes (25): UnsupportedParameter, _chat(), _collect(), _data_url(), fake(), _last_call(), make(), _make() (+17 more)

### Community 44 - "Device Manager Tests"
Cohesion: 0.17
Nodes (20): spec(), Clock, Events, _manager(), test_backend_unavailable_records_load_failed(), no_backend(), test_busy_model_not_evicted_waits_then_model_busy(), test_concurrent_requests_load_once() (+12 more)

### Community 45 - "OpenVINO Model Conversion"
Cohesion: 0.14
Nodes (16): fetch_source(), _isolated_deps(), main(), download_file(), download_repo(), file_url(), _headers(), repo_files() (+8 more)

### Community 46 - "Tasks: Routing & QA"
Cohesion: 0.08
Nodes (23): Capabilities Filter (tools/vision/json/stream/fim/type), project_allowed_models glob permission, Retryable runtime errors (model_busy, device_oom, device_unavailable), router_service.resolve, /v1/completions with suffix (FIM), GET /v1/images/files/{image_id}, image_controller / image_service, generated_images table (+15 more)

### Community 47 - "API v1 Integration Tests"
Cohesion: 0.13
Nodes (19): _request_rows(), test_chat_non_stream_shape_headers_and_log(), test_chat_stream_done_and_include_usage(), test_embeddings_base64_decodable_by_sdk(), test_fallback_recorded_and_all_failed_502(), test_fim_completion_autocomplete(), test_image_edits_multipart_image_to_image(), test_image_url_access_scoped_to_project() (+11 more)

### Community 48 - "Framework Examples & Backup"
Cohesion: 0.15
Nodes (9): _conn(), _counts(), main(), _run(), main(), _token_from_env(), main(), main() (+1 more)

### Community 49 - "Tasks: Setup & Core"
Cohesion: 0.11
Nodes (27): TASK-01 Setup Environment & Project Skeleton, Conda env llm-genai (Python 3.10-3.12), create_app() FastAPI app factory (app/main.py), scripts/env.bat, MVC project structure (app/ gateway + runtime/ Local Runtime), scripts/start-gateway.bat, TASK-02 Core: Config, Error Hierarchy, App Factory, get_settings() (lru_cache) (+19 more)

### Community 50 - "Profile: full"
Cohesion: 0.07
Nodes (26): is_enabled, is_pinned, is_enabled, is_pinned, is_enabled, is_pinned, is_enabled, is_pinned (+18 more)

### Community 51 - "Tasks: Usage & API v1"
Cohesion: 0.10
Nodes (19): RequestCtx / Attempt / Outcome, chat_service execute / execute_stream, Caller tracing (X-Caller-Task, X-Caller-Agent, metadata), chat_controller.create_chat_completion, converters to_unified / from_unified, Gateway response headers (X-Gateway-Provider/Model/Device/Attempts), Decimal Cost Formula, Orphan Sweeper (+11 more)

### Community 52 - "Seed Models: Models"
Cohesion: 0.08
Nodes (25): models, alias, artifact_path, artifact_sha256, context_window, convert, device, embedding_dimensions (+17 more)

### Community 53 - "Error Handling Tests"
Cohesion: 0.16
Nodes (17): _app(), _mnf(), _rl(), _Body, _client(), test_body_over_limit_by_content_length_is_413(), test_body_over_limit_chunked_is_413(), test_body_under_limit_passes() (+9 more)

### Community 54 - "OV Diffusion Backend"
Cohesion: 0.14
Nodes (6): InvalidRequestError, LoadResult, _decode_b64(), _int(), OVDiffusionBackend, _Params

### Community 55 - "Backend Threading Helpers"
Cohesion: 0.15
Nodes (5): ImageResult, iterate_in_thread(), put(), worker(), FakeBackend

### Community 56 - "Profile: ram16"
Cohesion: 0.08
Nodes (23): is_enabled, is_enabled, is_pinned, is_enabled, is_enabled, is_pinned, is_enabled, models (+15 more)

### Community 57 - "Test Config & Live Providers"
Cohesion: 0.11
Nodes (9): _db_reachable(), _dispose_engine(), migrated_db(), pytest_addoption(), pytest_collection_modifyitems(), client(), _require(), test_chat_non_stream_and_stream() (+1 more)

### Community 58 - "OV Diffusion Tests"
Cohesion: 0.17
Nodes (15): RequestCancelled, _Events, fake(), _loaded(), _png(), sd_spec(), test_cancel_stops_within_one_step(), test_cpu_device_and_bad_sha_rejected() (+7 more)

### Community 59 - "OpenAI SDK Examples"
Cohesion: 0.11
Nodes (8): images(), json_mode(), tools(), vision(), _client(), test_chat_stream_completions_models_images(), test_errors_map_to_sdk_exceptions(), serve()

### Community 60 - "Profile: remote-only"
Cohesion: 0.09
Nodes (21): is_enabled, is_enabled, is_enabled, is_enabled, is_enabled, models, local/qwen2.5-7b, local/qwen2.5-coder-1.5b (+13 more)

### Community 61 - "Load Tests & Port Wait"
Cohesion: 0.17
Nodes (10): main(), wait_port(), _duration(), fake_gateway(), _free_port(), _open_loop(), _pct(), _save() (+2 more)

### Community 62 - "Admin Integration Tests"
Cohesion: 0.12
Nodes (12): admin(), _audit_count(), _audits(), _project_id(), test_catalog_pricing_and_provider_auto_route(), test_key_allowed_models_override_project(), test_model_route_changes_apply_without_restart(), test_pin_over_budget_rejected_atomically() (+4 more)

### Community 63 - "Auth Integration Tests"
Cohesion: 0.29
Nodes (18): _bearer(), _chat(), _key(), _project(), test_admin_routes_require_admin_role(), test_auth_context_carries_allowed_model_patterns(), test_auth_context_limits_and_last_used(), test_cache_hit_is_fast_and_skips_db() (+10 more)

### Community 64 - "Hardware LLM Tests"
Cohesion: 0.17
Nodes (11): catalog_spec(), spec_for(), _call(), managers(), test_cancel_mid_stream_then_serves_next(), test_chat_stream_and_usage(), test_fim_on_npu_ttft(), test_json_object_always_valid_100() (+3 more)

### Community 65 - "SD NPU Tests & Artifacts"
Cohesion: 0.14
Nodes (9): sha256_artifact(), sha256_file(), _Events, _generate(), test_cancel_within_one_step(), test_image_to_image(), test_text_to_image_deterministic_25_steps(), make() (+1 more)

### Community 66 - "Task List & Milestones"
Cohesion: 0.16
Nodes (18): Milestones M1-M6, Task list - LLM Gateway (PRD v2.0), Critical path 01-02-04-09-10-11-13-15-14-20, TASK-09 Hardware probe, model download/convert & measure, requirements-local.txt (openvino, openvino-genai, optimum-intel, nncf pinned), TASK-10 Local Runtime + Device/VRAM Manager, TASK-11 Backend OpenVINO GenAI (Qwen text, code/FIM, vision), TASK-12 Backend OpenVINO SD v1.5 on NPU (+10 more)

### Community 67 - "Seed Models: Local Params"
Cohesion: 0.10
Nodes (21): allowed_sizes, cache_dir, cached_input_cost_per_mtok, default_steps, default_strength, device, drop_params, fim_max_prompt_tokens (+13 more)

### Community 68 - "DB Model Tests"
Cohesion: 0.21
Nodes (14): ModelRouteTarget, _count(), _load_manage(), _make_chain(), _seed_data(), test_delete_project_cascades_keys_and_nulls_requests(), test_delete_request_cascades(), test_insert_chain_and_defaults() (+6 more)

### Community 69 - "Tasks: Errors & Providers"
Cohesion: 0.17
Nodes (20): CapabilityNotSupported, error_handler middleware, GatewayError hierarchy (app/utils/errors.py), Local model errors (ModelBusy, DeviceOOM, DeviceUnavailable), UpstreamError family (UpstreamTimeout, UpstreamRateLimited, UpstreamBadRequest), aiter_sse upstream SSE parser, BaseProvider ABC (app/services/providers/base.py), Fake provider (tests/fakes/fake_provider.py) (+12 more)

### Community 70 - "Tasks: Deployment & Health"
Cohesion: 0.11
Nodes (19): First Token Timeout (60s remote / 120s local), TASK-18 Health Check & Metrics, /health/live, /health/ready (ready|degraded|not_ready), Local Runtime health (warming_up), manage.py verify-models, TASK-21/22 Deployment without/with Traefik, Local Runtime 127.0.0.1:8100 (GPU llama-cpp, NPU OpenVINO) (+11 more)

### Community 71 - "Model Memory Measurement"
Cohesion: 0.18
Nodes (8): DeviceMemory, measure_llm(), PeakSampler, main(), _png(), run(), generate(), _to_tensor()

### Community 72 - "App Factory & Test Setup"
Cohesion: 0.16
Nodes (8): create_app(), api(), Api, build_fake_gateway(), factory(), default_project_keys(), _project_key(), test_admin_verify_endpoint()

### Community 73 - "OpenAI Provider Tests"
Cohesion: 0.25
Nodes (15): ImageURL, _provider(), _req(), _status(), test_bad_request_forwards_upstream_message(), test_chat_payload_has_no_none_fields_and_maps_response(), test_drop_params_removes_sampling_fields_unsupported_by_model(), test_embeddings() (+7 more)

### Community 74 - "Admin Query Pagination"
Cohesion: 0.29
Nodes (11): decode_cursor(), encode_cursor(), get_request(), _jsonable(), _limit(), list_audit(), list_requests(), list_runtime_events() (+3 more)

### Community 75 - "Inference Service"
Cohesion: 0.23
Nodes (6): DeviceUnavailable, observe_generation(), Lease, InferenceService, _with_warnings(), x_runtime()

### Community 76 - "Helper Utilities"
Cohesion: 0.22
Nodes (13): calc_cost(), client_ip(), _dec(), estimate_tokens(), glob_match(), _header(), _text_len(), _scope() (+5 more)

### Community 77 - "Request Converters"
Cohesion: 0.21
Nodes (14): _capabilities(), chat_capabilities(), chat_response(), chat_to_unified(), completion_capabilities(), completion_response(), completion_to_unified(), image_meta() (+6 more)

### Community 78 - "API Key Crypto"
Cohesion: 0.21
Nodes (10): generate_api_key(), hash_api_key(), parse_key_prefix(), _pepper(), verify(), test_generate_format_and_hash(), test_hash_depends_on_pepper(), test_keys_are_unique() (+2 more)

### Community 79 - "Local Backend Interface"
Cohesion: 0.17
Nodes (3): LocalBackend, backend_class(), create_backend()

### Community 80 - "Request Context Middleware"
Cohesion: 0.15
Nodes (5): _header(), _incoming_request_id(), RequestContextMiddleware, new_request_id(), test_new_request_id_is_uuid7_and_ordered()

### Community 81 - "Client Integration Docs"
Cohesion: 0.15
Nodes (16): API key lgw_<prefix>_<secret> (HMAC + pepper), X-Caller-Task / X-Caller-Agent headers, X-Gateway-Model / Provider / Device response headers, api_keys table, Database ERD (PostgreSQL llm_gateway), generated_images table, projects table, quotas table (+8 more)

### Community 82 - "Runtime Event Service"
Cohesion: 0.17
Nodes (5): on_event(), _as_uuid(), EventService, _BrokenSession, test_record_falls_back_to_jsonl_when_db_down()

### Community 83 - "Local Benchmarks"
Cohesion: 0.26
Nodes (10): bench_chat(), bench_fim(), bench_image(), load_ms(), main(), pct(), png_data_url(), render() (+2 more)

### Community 84 - "Alembic Migrations"
Cohesion: 0.17
Nodes (9): downgrade(), upgrade(), downgrade(), _in(), upgrade(), downgrade(), _in(), upgrade() (+1 more)

### Community 85 - "Error Handler Middleware"
Cohesion: 0.30
Nodes (8): gateway_error_response(), _handle_gateway_error(), _handle_http_exception(), _handle_unexpected(), _handle_validation_error(), _loc_to_param(), register_error_handlers(), _request_id()

### Community 86 - "Config Validation Tests"
Cohesion: 0.27
Nodes (11): ConfigError, load_settings(), test_budgets_and_body_bytes(), test_cors_origins_comma_separated(), test_cpu_fallback_in_prod_warns(), test_database_url_must_be_async_and_not_placeholder(), test_missing_database_url(), test_provider_secret() (+3 more)

### Community 87 - "Admin Usage Verification"
Cohesion: 0.23
Nodes (4): verify_usage(), provider_billing(), usage(), usage_verify()

### Community 88 - "Profile Integration Tests"
Cohesion: 0.25
Nodes (9): _manage(), _profile(), _state(), test_apply_ram16_then_full_roundtrip(), test_full_profile_matches_seed_routes(), test_invalid_profile_rejected_without_changes(), test_remote_only_disables_runtime_and_local_routes(), catalog() (+1 more)

### Community 89 - "Health Ready Tests"
Cohesion: 0.35
Nodes (10): _admin_key(), _app(), _client(), _runtime_handler(), test_degraded_when_runtime_down_or_pinned_missing(), test_details_hidden_for_remote_clients(), test_live_fast(), test_metrics_merges_runtime_metrics() (+2 more)

### Community 91 - "Release & DB Decisions"
Cohesion: 0.22
Nodes (9): Release 0.1.0 (2026-10-28), audit_logs table, models table (runtime catalog source of truth), providers table, runtime_events table, Operational profiles (remote-only, ram16, full), Custom provider adapters (openai / anthropic / gemini), Load test results (fake provider, 1 worker) (+1 more)

### Community 92 - "NPU & FIM Model Notes"
Cohesion: 0.22
Nodes (10): Continue Qwen FIM prompt template, Default virtual routes (fast, smart, local, code, autocomplete, vision, image, embed-default), local/qwen2.5-7b, local/qwen2.5-coder-1.5b (NPU, FIM), local/qwen2.5-coder-7b, local/qwen2-vl-2b (vision), Remote model seed (Claude Sonnet/Haiku, GPT-5, Gemini Flash, embeddings), local/sd-1.5 (Stable Diffusion v1.5, NPU) (+2 more)

### Community 93 - "Deployment Mode A & Device Budget"
Cohesion: 0.22
Nodes (11): Deployment Mode A (no Traefik), Runtime supervisor (start-runtime.bat, max 5 restarts), Device probe (Core Ultra 5 225, Intel iGPU, NPU AI Boost), Orphan sweeper (pending -> error after 10 min), llm_gateway (OpenAI-compatible LLM gateway), Local Runtime (127.0.0.1:8100), Gateway endpoints (/v1, /admin, /health, /metrics), start-all.bat / stop-all.bat (+3 more)

### Community 94 - "Local Smoke Script"
Cohesion: 0.45
Nodes (10): _chat_prompt(), code_chat(), _config(), _device(), fim(), _generate(), main(), _pipe() (+2 more)

### Community 95 - "Health Service"
Cohesion: 0.26
Nodes (3): check_db(), HealthService, render()

### Community 96 - "Seed Models: Providers"
Cohesion: 0.17
Nodes (12): adapter, headers, X-Title, providers, api_key_env, base_url, code, config (+4 more)

### Community 97 - "Client & Proxy Docs"
Cohesion: 0.18
Nodes (10): Coding assistant integration (Continue, Cline, Aider, Open WebUI, Cursor), Error format {error: message,type,code,param} + retry table, Framework integration (LangChain, LlamaIndex, CrewAI, AutoGen), OpenAI-compatible client integration (base URL /v1, lgw_ key, route as model), request_attempts table, --behind-proxy (proxy_headers, TRUST_PROXY), Deployment Mode B (Traefik :8080, admin ipAllowList, rate limit), Optional self-signed TLS (websecure entrypoint) (+2 more)

### Community 100 - "Secret Scan Script"
Cohesion: 0.38
Nodes (7): _is_log(), main(), mask(), scan_db(), scan_logs(), scan_text(), _sync_url()

### Community 101 - "Admin Requests Routes"
Cohesion: 0.42
Nodes (4): list_requests(), get_request(), list_requests(), RequestFilter

### Community 102 - "Admin Runtime Routes"
Cohesion: 0.33
Nodes (5): runtime_events(), runtime_load(), runtime_status(), runtime_unload(), swap_stats()

### Community 103 - "Console Route"
Cohesion: 0.44
Nodes (5): console_asset(), console_page(), _forbidden(), _hostname(), is_local_request()

### Community 104 - "Migrations Env"
Cohesion: 0.36
Nodes (5): _configure(), _database_url(), do_run_migrations(), run_async_migrations(), run_migrations_offline()

### Community 105 - "JS SDK Example"
Cohesion: 0.25
Nodes (7): client, dependencies, openai@^6.0.0, name, private, type, openai

### Community 106 - "Provider Test Fixtures"
Cohesion: 0.25
Nodes (4): mock_http(), make(), Recorder, settings()

### Community 108 - "Tasks: Admin API & Audit"
Cohesion: 0.29
Nodes (6): runtime_events table, Admin API (/admin endpoints), Cursor pagination (created_at,id), If-Match optimistic concurrency on PATCH, Runtime admin endpoints (status/load/unload/events/swap-stats), maintenance_service (purge_* retention)

### Community 109 - "Custom Provider Tests"
Cohesion: 0.25
Nodes (3): admin(), test_add_custom_provider_model_route_and_call_it(), test_secret_exfiltration_and_bad_config_rejected()

### Community 110 - "Hermes Tool Prompt"
Cohesion: 0.48
Nodes (3): _call_block(), render_hermes_messages(), tools_system_block()

### Community 111 - "Seed Models: Routes"
Cohesion: 0.29
Nodes (6): routes, alias, description, targets, model, priority

### Community 112 - "Admin Console Feature"
Cohesion: 0.33
Nodes (6): Konsol LLM Gateway page (index.html), Admin Console (/console), GET /admin/env-status, model_routes / model_route_targets tables, Per-key allowed model patterns, <provider>/auto routes

### Community 118 - "SD1.5 img2img Smoke"
Cohesion: 0.50
Nodes (5): SD1.5 Image-to-Image Smoke Test Output, Image-to-Image (img2img) Generation, Image Generation Smoke Test, Stable Diffusion 1.5, Surreal Painted Scene (hooded figure with ornate ring, starry blue landscape, moon)

### Community 120 - "SD1.5 txt2img Smoke"
Cohesion: 0.67
Nodes (4): SD1.5 Text-to-Image Smoke Test Output, Image Generation Smoke Test, Stable Diffusion 1.5, Text-to-Image Generation

### Community 121 - "Vision Smoke Input"
Cohesion: 0.67
Nodes (4): Text 'GATEWAY 42' (OCR target), Vision Smoke Test Input Image, Red Rectangle (color recognition target), Vision Model Smoke Test

### Community 122 - "SD Component Devices"
Cohesion: 0.50
Nodes (4): text_encoder, unet, vae, component_devices

## Ambiguous Edges - Review These
- `llama-cpp-python (GGUF on GPU)` → `TASK-11 switch from llama-cpp-python to OpenVINO GenAI (28 Oct 2026)`  [AMBIGUOUS]
  llm_gateway_docs_v2/tasks/README.md · relation: conceptually_related_to
- `Conda env llm-genai (Python 3.10-3.12)` → `Revision 28 Oct 2026: Qwen + SD v1.5 on OpenVINO GPU/NPU only (no llama.cpp, no CPU)`  [AMBIGUOUS]
  llm_gateway_docs_v2/tasks/TASK-09-hardware-model-acquisition.md · relation: conceptually_related_to
- `scripts/seed_models.yaml (local model catalog & routes)` → `Revision 28 Oct 2026: Qwen + SD v1.5 on OpenVINO GPU/NPU only (no llama.cpp, no CPU)`  [AMBIGUOUS]
  llm_gateway_docs_v2/tasks/TASK-09-hardware-model-acquisition.md · relation: conceptually_related_to
- `Revision 28 Oct 2026: Qwen + SD v1.5 on OpenVINO GPU/NPU only (no llama.cpp, no CPU)` → `LocalBackend ABC (runtime/backends/base.py)`  [AMBIGUOUS]
  llm_gateway_docs_v2/tasks/TASK-10-local-runtime-device-manager.md · relation: conceptually_related_to

## Knowledge Gaps
- **72 isolated node(s):** `llm_gateway`, `GET /admin/env-status`, `start-all.bat / stop-all.bat`, `check.bat quality gate (ruff, mypy, pytest coverage >= 70%, secret scan)`, `Gateway endpoints (/v1, /admin, /health, /metrics)` (+67 more)
  These have ≤1 connection - possible missing edges or undocumented components. (Counts symbols only; 899 node(s) total have ≤1 connection when file, concept and rationale nodes are included.)
- **35 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `TASK-09 Hardware probe, model download/convert & measure` connect `Task List & Milestones` to `Tasks: Local Runtime & DB`, `Model Memory Measurement`, `Tasks: Setup & Core`, `Local Smoke Script`, `PRD Concepts`?**
  _High betweenness centrality (0.063) - this node is a cross-community bridge._
- **Are the 75 inferred relationships involving `AuthContext` (e.g. with `create_model()` and `create_provider()`) actually correct?**
  _`AuthContext` has 75 INFERRED edges - model-reasoned connections that need verification._
- **What connects `llm_gateway`, `GET /admin/env-status`, `start-all.bat / stop-all.bat` to the rest of the system?**
  _72 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `Model & Project Services` be split into smaller, more focused modules?**
  _Cohesion score 0.059535678678250964 - nodes in this community are weakly interconnected._
- **Why does `AuthContext` connect `Public API Controllers` to `Model & Project Services`, `Chat/Image Service Context`, `Rate Limit & Quota`, `Image Controller`, `Admin Catalog CRUD`, `Admin Runtime Routes`, `Router Service & Fallback`, `API Key Service`, `Usage Accounting`, `Usage Endpoint`, `Admin Keys & Schemas`, `Chat Completion Controller`, `Admin Quota Routes`, `Auth Test Fixtures`, `Admin Projects & Observe`, `Admin Maintenance Routes`, `Auth Integration Tests`?**
  _High betweenness centrality (0.041) - this node is a cross-community bridge._

### Low-confidence Hints
_AMBIGUOUS edges — the extractor was unsure. Verify before acting on these._

- **What is the exact relationship between `llama-cpp-python (GGUF on GPU)` and `TASK-11 switch from llama-cpp-python to OpenVINO GenAI (28 Oct 2026)`?**
  _Edge tagged AMBIGUOUS (relation: conceptually_related_to) - confidence is low._
- **What is the exact relationship between `Conda env llm-genai (Python 3.10-3.12)` and `Revision 28 Oct 2026: Qwen + SD v1.5 on OpenVINO GPU/NPU only (no llama.cpp, no CPU)`?**
  _Edge tagged AMBIGUOUS (relation: conceptually_related_to) - confidence is low._