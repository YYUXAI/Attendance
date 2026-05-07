--
-- PostgreSQL database dump
--

\restrict WwjWiC5LGUfJI7HAU1I0ezkDAiRkHF4TXbxKim8uS53iCDeMaBg8bXKlybTqty9

-- Dumped from database version 18.3
-- Dumped by pg_dump version 18.3

-- Started on 2026-05-07 15:52:42

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET transaction_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- TOC entry 226 (class 1259 OID 17847)
-- Name: admin_list; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.admin_list (
    id bigint NOT NULL,
    admin_employee_id character varying(64)
);


ALTER TABLE public.admin_list OWNER TO postgres;

--
-- TOC entry 5321 (class 0 OID 0)
-- Dependencies: 226
-- Name: TABLE admin_list; Type: COMMENT; Schema: public; Owner: postgres
--

COMMENT ON TABLE public.admin_list IS '管理员名单';


--
-- TOC entry 225 (class 1259 OID 17846)
-- Name: admin_list_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.admin_list_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.admin_list_id_seq OWNER TO postgres;

--
-- TOC entry 5322 (class 0 OID 0)
-- Dependencies: 225
-- Name: admin_list_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.admin_list_id_seq OWNED BY public.admin_list.id;


--
-- TOC entry 248 (class 1259 OID 17952)
-- Name: approval_task_queue; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.approval_task_queue (
    id bigint NOT NULL,
    application_type character varying(50),
    application_id bigint,
    application_submitted_at timestamp with time zone,
    approval_level integer,
    applicant_employee_id character varying(64),
    approver_employee_id character varying(64),
    task_status character varying(50),
    approval_result character varying(50),
    approved_at timestamp with time zone,
    approver_remark text,
    task_created_at timestamp with time zone,
    CONSTRAINT ck_approval_task_queue_approval_result CHECK (((approval_result IS NULL) OR ((approval_result)::text = ANY ((ARRAY['APPROVED'::character varying, 'REJECTED'::character varying, 'SKIPPED'::character varying, 'NONE'::character varying])::text[])))),
    CONSTRAINT ck_approval_task_queue_task_status CHECK (((task_status IS NULL) OR ((task_status)::text = ANY ((ARRAY['PENDING'::character varying, 'PROCESSING'::character varying, 'APPROVED_DONE'::character varying, 'REJECTED_DONE'::character varying, 'AUTO_SKIPPED'::character varying, 'CANCELLED'::character varying, 'FAILED'::character varying])::text[]))))
);


ALTER TABLE public.approval_task_queue OWNER TO postgres;

--
-- TOC entry 5323 (class 0 OID 0)
-- Dependencies: 248
-- Name: TABLE approval_task_queue; Type: COMMENT; Schema: public; Owner: postgres
--

COMMENT ON TABLE public.approval_task_queue IS '审批任务队列';


--
-- TOC entry 247 (class 1259 OID 17951)
-- Name: approval_task_queue_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.approval_task_queue_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.approval_task_queue_id_seq OWNER TO postgres;

--
-- TOC entry 5324 (class 0 OID 0)
-- Dependencies: 247
-- Name: approval_task_queue_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.approval_task_queue_id_seq OWNED BY public.approval_task_queue.id;


--
-- TOC entry 242 (class 1259 OID 17923)
-- Name: audit_results; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.audit_results (
    id bigint NOT NULL,
    employee_id character varying(64),
    shift_id bigint,
    organization_id bigint,
    audit_date date,
    audit_stage character varying(50),
    checked_at timestamp with time zone,
    valid_clock_time timestamp with time zone,
    result character varying(50),
    CONSTRAINT ck_audit_results_audit_stage CHECK (((audit_stage IS NULL) OR ((audit_stage)::text = ANY ((ARRAY['CHECKIN'::character varying, 'CHECKOUT'::character varying, 'BREAK'::character varying])::text[])))),
    CONSTRAINT ck_audit_results_result CHECK (((result IS NULL) OR ((result)::text = ANY ((ARRAY['NORMAL'::character varying, 'LATE'::character varying, 'EARLY_LEAVE'::character varying, 'ABSENT'::character varying, 'ON_LEAVE'::character varying, 'TEMPORARY_LEAVE'::character varying, 'EXEMPT'::character varying])::text[]))))
);


ALTER TABLE public.audit_results OWNER TO postgres;

--
-- TOC entry 5325 (class 0 OID 0)
-- Dependencies: 242
-- Name: TABLE audit_results; Type: COMMENT; Schema: public; Owner: postgres
--

COMMENT ON TABLE public.audit_results IS '审计结果表';


--
-- TOC entry 241 (class 1259 OID 17922)
-- Name: audit_results_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.audit_results_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.audit_results_id_seq OWNER TO postgres;

--
-- TOC entry 5326 (class 0 OID 0)
-- Dependencies: 241
-- Name: audit_results_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.audit_results_id_seq OWNED BY public.audit_results.id;


--
-- TOC entry 250 (class 1259 OID 17962)
-- Name: audit_task_queue; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.audit_task_queue (
    id bigint NOT NULL,
    log_id bigint,
    audit_started_at timestamp with time zone,
    employee_id character varying(64),
    target_date date,
    audit_stage character varying(50),
    audit_result character varying(50),
    created_at timestamp with time zone,
    processed_at timestamp with time zone,
    retry_count integer DEFAULT 0,
    error_message text,
    task_status character varying(50),
    CONSTRAINT ck_audit_task_queue_audit_result CHECK (((audit_result IS NULL) OR ((audit_result)::text = ANY ((ARRAY['NORMAL'::character varying, 'LATE'::character varying, 'EARLY_LEAVE'::character varying, 'ABSENT'::character varying, 'ON_LEAVE'::character varying, 'TEMPORARY_LEAVE'::character varying, 'EXEMPT'::character varying, 'NONE'::character varying])::text[])))),
    CONSTRAINT ck_audit_task_queue_audit_stage CHECK (((audit_stage IS NULL) OR ((audit_stage)::text = ANY ((ARRAY['CHECKIN'::character varying, 'CHECKOUT'::character varying, 'BREAK'::character varying])::text[])))),
    CONSTRAINT ck_audit_task_queue_task_status CHECK (((task_status IS NULL) OR ((task_status)::text = ANY ((ARRAY['PENDING'::character varying, 'PROCESSING'::character varying, 'DONE'::character varying, 'FAILED'::character varying, 'SKIPPED'::character varying, 'CANCELLED'::character varying])::text[]))))
);


ALTER TABLE public.audit_task_queue OWNER TO postgres;

--
-- TOC entry 5327 (class 0 OID 0)
-- Dependencies: 250
-- Name: TABLE audit_task_queue; Type: COMMENT; Schema: public; Owner: postgres
--

COMMENT ON TABLE public.audit_task_queue IS '审计任务队列';


--
-- TOC entry 249 (class 1259 OID 17961)
-- Name: audit_task_queue_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.audit_task_queue_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.audit_task_queue_id_seq OWNER TO postgres;

--
-- TOC entry 5328 (class 0 OID 0)
-- Dependencies: 249
-- Name: audit_task_queue_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.audit_task_queue_id_seq OWNED BY public.audit_task_queue.id;


--
-- TOC entry 232 (class 1259 OID 17875)
-- Name: clock_records; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.clock_records (
    id bigint NOT NULL,
    chat_id bigint,
    file_id text,
    tg_id bigint,
    employee_id character varying(64),
    shift_id bigint,
    clock_time timestamp with time zone
);


ALTER TABLE public.clock_records OWNER TO postgres;

--
-- TOC entry 5329 (class 0 OID 0)
-- Dependencies: 232
-- Name: TABLE clock_records; Type: COMMENT; Schema: public; Owner: postgres
--

COMMENT ON TABLE public.clock_records IS '打卡记录表';


--
-- TOC entry 231 (class 1259 OID 17874)
-- Name: clock_records_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.clock_records_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.clock_records_id_seq OWNER TO postgres;

--
-- TOC entry 5330 (class 0 OID 0)
-- Dependencies: 231
-- Name: clock_records_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.clock_records_id_seq OWNED BY public.clock_records.id;


--
-- TOC entry 234 (class 1259 OID 17885)
-- Name: effective_leave_days; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.effective_leave_days (
    id bigint NOT NULL,
    employee_id character varying(64),
    leave_date date,
    shift_id bigint,
    leave_reason text,
    application_remark text,
    application_id bigint
);


ALTER TABLE public.effective_leave_days OWNER TO postgres;

--
-- TOC entry 5331 (class 0 OID 0)
-- Dependencies: 234
-- Name: TABLE effective_leave_days; Type: COMMENT; Schema: public; Owner: postgres
--

COMMENT ON TABLE public.effective_leave_days IS '已生效休假名单';


--
-- TOC entry 233 (class 1259 OID 17884)
-- Name: effective_leave_days_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.effective_leave_days_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.effective_leave_days_id_seq OWNER TO postgres;

--
-- TOC entry 5332 (class 0 OID 0)
-- Dependencies: 233
-- Name: effective_leave_days_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.effective_leave_days_id_seq OWNED BY public.effective_leave_days.id;


--
-- TOC entry 236 (class 1259 OID 17895)
-- Name: effective_temporary_leaves; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.effective_temporary_leaves (
    id bigint NOT NULL,
    employee_id character varying(64),
    effective_date timestamp with time zone,
    shift_id bigint,
    reason_remark text,
    leave_start_at timestamp with time zone,
    leave_end_at timestamp with time zone,
    application_id bigint
);


ALTER TABLE public.effective_temporary_leaves OWNER TO postgres;

--
-- TOC entry 5333 (class 0 OID 0)
-- Dependencies: 236
-- Name: TABLE effective_temporary_leaves; Type: COMMENT; Schema: public; Owner: postgres
--

COMMENT ON TABLE public.effective_temporary_leaves IS '已生效离岗报备';


--
-- TOC entry 235 (class 1259 OID 17894)
-- Name: effective_temporary_leaves_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.effective_temporary_leaves_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.effective_temporary_leaves_id_seq OWNER TO postgres;

--
-- TOC entry 5334 (class 0 OID 0)
-- Dependencies: 235
-- Name: effective_temporary_leaves_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.effective_temporary_leaves_id_seq OWNED BY public.effective_temporary_leaves.id;


--
-- TOC entry 246 (class 1259 OID 17941)
-- Name: event_logs; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.event_logs (
    id bigint NOT NULL,
    event_name character varying(100),
    related_event_name character varying(100),
    result character varying(50),
    related_event_id bigint,
    created_at timestamp with time zone,
    processed_at timestamp with time zone,
    retry_count integer DEFAULT 0,
    error_message text,
    CONSTRAINT ck_event_logs_result CHECK (((result IS NULL) OR ((result)::text = ANY ((ARRAY['CREATED'::character varying, 'DISPATCHED'::character varying, 'PROCESSED'::character varying, 'FAILED'::character varying, 'IGNORED'::character varying])::text[]))))
);


ALTER TABLE public.event_logs OWNER TO postgres;

--
-- TOC entry 5335 (class 0 OID 0)
-- Dependencies: 246
-- Name: TABLE event_logs; Type: COMMENT; Schema: public; Owner: postgres
--

COMMENT ON TABLE public.event_logs IS '事件日志';


--
-- TOC entry 245 (class 1259 OID 17940)
-- Name: event_logs_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.event_logs_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.event_logs_id_seq OWNER TO postgres;

--
-- TOC entry 5336 (class 0 OID 0)
-- Dependencies: 245
-- Name: event_logs_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.event_logs_id_seq OWNED BY public.event_logs.id;


--
-- TOC entry 228 (class 1259 OID 17855)
-- Name: leave_applications; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.leave_applications (
    id bigint NOT NULL,
    employee_id character varying(64),
    organization_id bigint,
    shift_id bigint,
    start_at timestamp with time zone,
    end_at timestamp with time zone,
    leave_reason text,
    remark text,
    status character varying(50),
    completed_at timestamp with time zone,
    created_at timestamp with time zone,
    CONSTRAINT ck_leave_applications_status CHECK (((status IS NULL) OR ((status)::text = ANY ((ARRAY['SUBMITTED'::character varying, 'APPROVING'::character varying, 'APPROVED'::character varying, 'REJECTED'::character varying, 'CANCELLED'::character varying, 'EFFECTIVE'::character varying, 'COMPLETED'::character varying, 'EXPIRED'::character varying])::text[]))))
);


ALTER TABLE public.leave_applications OWNER TO postgres;

--
-- TOC entry 5337 (class 0 OID 0)
-- Dependencies: 228
-- Name: TABLE leave_applications; Type: COMMENT; Schema: public; Owner: postgres
--

COMMENT ON TABLE public.leave_applications IS '休假申请原始记录';


--
-- TOC entry 227 (class 1259 OID 17854)
-- Name: leave_applications_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.leave_applications_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.leave_applications_id_seq OWNER TO postgres;

--
-- TOC entry 5338 (class 0 OID 0)
-- Dependencies: 227
-- Name: leave_applications_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.leave_applications_id_seq OWNED BY public.leave_applications.id;


--
-- TOC entry 254 (class 1259 OID 17984)
-- Name: notification_queue; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.notification_queue (
    id bigint NOT NULL,
    log_id bigint,
    notify_tg_id bigint,
    template_id bigint,
    reply_content text,
    attachment_id text,
    delivery_result character varying(50),
    created_at timestamp with time zone,
    processed_at timestamp with time zone,
    retry_count integer DEFAULT 0,
    error_message text,
    task_status character varying(50),
    CONSTRAINT ck_notification_queue_delivery_result CHECK (((delivery_result IS NULL) OR ((delivery_result)::text = ANY ((ARRAY['SENT'::character varying, 'FAILED'::character varying, 'UNDELIVERABLE'::character varying, 'NONE'::character varying])::text[])))),
    CONSTRAINT ck_notification_queue_task_status CHECK (((task_status IS NULL) OR ((task_status)::text = ANY ((ARRAY['PENDING'::character varying, 'PROCESSING'::character varying, 'RETRYING'::character varying, 'CANCELLED'::character varying, 'SKIPPED'::character varying, 'DONE'::character varying])::text[]))))
);


ALTER TABLE public.notification_queue OWNER TO postgres;

--
-- TOC entry 5339 (class 0 OID 0)
-- Dependencies: 254
-- Name: TABLE notification_queue; Type: COMMENT; Schema: public; Owner: postgres
--

COMMENT ON TABLE public.notification_queue IS '通知任务队列';


--
-- TOC entry 253 (class 1259 OID 17983)
-- Name: notification_queue_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.notification_queue_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.notification_queue_id_seq OWNER TO postgres;

--
-- TOC entry 5340 (class 0 OID 0)
-- Dependencies: 253
-- Name: notification_queue_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.notification_queue_id_seq OWNED BY public.notification_queue.id;


--
-- TOC entry 220 (class 1259 OID 17821)
-- Name: organizations; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.organizations (
    id bigint NOT NULL,
    department_name character varying(255),
    highest_responsible_employee_id character varying(64),
    leader_employee_id character varying(64)
);


ALTER TABLE public.organizations OWNER TO postgres;

--
-- TOC entry 5341 (class 0 OID 0)
-- Dependencies: 220
-- Name: TABLE organizations; Type: COMMENT; Schema: public; Owner: postgres
--

COMMENT ON TABLE public.organizations IS '组织表';


--
-- TOC entry 219 (class 1259 OID 17820)
-- Name: organizations_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.organizations_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.organizations_id_seq OWNER TO postgres;

--
-- TOC entry 5342 (class 0 OID 0)
-- Dependencies: 219
-- Name: organizations_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.organizations_id_seq OWNED BY public.organizations.id;


--
-- TOC entry 238 (class 1259 OID 17905)
-- Name: qc_exemption_fixed_list; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.qc_exemption_fixed_list (
    id bigint NOT NULL,
    shift_id bigint,
    employee_id character varying(64),
    remark text
);


ALTER TABLE public.qc_exemption_fixed_list OWNER TO postgres;

--
-- TOC entry 5343 (class 0 OID 0)
-- Dependencies: 238
-- Name: TABLE qc_exemption_fixed_list; Type: COMMENT; Schema: public; Owner: postgres
--

COMMENT ON TABLE public.qc_exemption_fixed_list IS '质检固定免检名单';


--
-- TOC entry 237 (class 1259 OID 17904)
-- Name: qc_exemption_fixed_list_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.qc_exemption_fixed_list_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.qc_exemption_fixed_list_id_seq OWNER TO postgres;

--
-- TOC entry 5344 (class 0 OID 0)
-- Dependencies: 237
-- Name: qc_exemption_fixed_list_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.qc_exemption_fixed_list_id_seq OWNED BY public.qc_exemption_fixed_list.id;


--
-- TOC entry 244 (class 1259 OID 17931)
-- Name: qc_results; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.qc_results (
    id bigint NOT NULL,
    employee_id character varying(64),
    shift_id bigint,
    organization_id bigint,
    qc_date date,
    qc_round integer,
    checked_at timestamp with time zone,
    completed_at timestamp with time zone,
    result character varying(50),
    attachment_id text,
    CONSTRAINT ck_qc_results_result CHECK (((result IS NULL) OR ((result)::text = ANY ((ARRAY['PASS'::character varying, 'FAIL'::character varying, 'TIMEOUT'::character varying, 'EXEMPT'::character varying])::text[]))))
);


ALTER TABLE public.qc_results OWNER TO postgres;

--
-- TOC entry 5345 (class 0 OID 0)
-- Dependencies: 244
-- Name: TABLE qc_results; Type: COMMENT; Schema: public; Owner: postgres
--

COMMENT ON TABLE public.qc_results IS '质检结果表';


--
-- TOC entry 243 (class 1259 OID 17930)
-- Name: qc_results_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.qc_results_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.qc_results_id_seq OWNER TO postgres;

--
-- TOC entry 5346 (class 0 OID 0)
-- Dependencies: 243
-- Name: qc_results_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.qc_results_id_seq OWNED BY public.qc_results.id;


--
-- TOC entry 252 (class 1259 OID 17973)
-- Name: qc_task_queue; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.qc_task_queue (
    id bigint NOT NULL,
    log_id bigint,
    employee_id character varying(64),
    shift_id bigint,
    qc_date date,
    qc_round integer,
    status character varying(50),
    task_result character varying(50),
    created_at timestamp with time zone,
    processed_at timestamp with time zone,
    retry_count integer DEFAULT 0,
    error_message text,
    first_private_notify_sent_at timestamp with time zone,
    pending_confirm_file_id text,
    CONSTRAINT ck_qc_task_queue_status CHECK (((status IS NULL) OR ((status)::text = ANY ((ARRAY['PENDING'::character varying, 'NOTIFIED'::character varying, 'WAITING_SUBMISSION'::character varying, 'SUBMITTED'::character varying, 'PROCESSING'::character varying, 'COMPLETED'::character varying, 'TIMEOUT'::character varying, 'FAILED'::character varying, 'CANCELLED'::character varying, 'SKIPPED'::character varying])::text[])))),
    CONSTRAINT ck_qc_task_queue_task_result CHECK (((task_result IS NULL) OR ((task_result)::text = ANY ((ARRAY['PASS'::character varying, 'FAIL'::character varying, 'TIMEOUT'::character varying, 'EXEMPT'::character varying, 'INVALID_ATTACHMENT'::character varying, 'NONE'::character varying])::text[]))))
);


ALTER TABLE public.qc_task_queue OWNER TO postgres;

--
-- TOC entry 5347 (class 0 OID 0)
-- Dependencies: 252
-- Name: TABLE qc_task_queue; Type: COMMENT; Schema: public; Owner: postgres
--

COMMENT ON TABLE public.qc_task_queue IS '质检任务队列';


--
-- TOC entry 251 (class 1259 OID 17972)
-- Name: qc_task_queue_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.qc_task_queue_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.qc_task_queue_id_seq OWNER TO postgres;

--
-- TOC entry 5348 (class 0 OID 0)
-- Dependencies: 251
-- Name: qc_task_queue_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.qc_task_queue_id_seq OWNED BY public.qc_task_queue.id;


--
-- TOC entry 224 (class 1259 OID 17839)
-- Name: registrations; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.registrations (
    id bigint NOT NULL,
    employee_id character varying(64),
    tg_id bigint,
    english_name character varying(128),
    registered_at timestamp with time zone,
    registered_chat_id bigint,
    tg_username character varying(128),
    organization_id bigint,
    shift_id bigint
);


ALTER TABLE public.registrations OWNER TO postgres;

--
-- TOC entry 5349 (class 0 OID 0)
-- Dependencies: 224
-- Name: TABLE registrations; Type: COMMENT; Schema: public; Owner: postgres
--

COMMENT ON TABLE public.registrations IS '注册信息表';


--
-- TOC entry 223 (class 1259 OID 17838)
-- Name: registrations_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.registrations_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.registrations_id_seq OWNER TO postgres;

--
-- TOC entry 5350 (class 0 OID 0)
-- Dependencies: 223
-- Name: registrations_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.registrations_id_seq OWNED BY public.registrations.id;


--
-- TOC entry 222 (class 1259 OID 17829)
-- Name: shifts; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.shifts (
    id bigint NOT NULL,
    checkin_time time without time zone,
    checkout_time time without time zone,
    timezone character varying(64),
    is_overnight boolean,
    attendance_group_id bigint,
    qc_trigger_interval interval,
    qc_draw_count integer,
    qc_example_file_id text,
    attendance_flex_interval interval,
    max_late_early_tolerance interval,
    qc_enabled boolean,
    CONSTRAINT ck_shifts_timezone CHECK (((timezone IS NULL) OR ((timezone)::text = ANY ((ARRAY['Asia/Shanghai'::character varying, 'Asia/Kuala_Lumpur'::character varying, 'Asia/Bangkok'::character varying, 'Asia/Dubai'::character varying])::text[]))))
);


ALTER TABLE public.shifts OWNER TO postgres;

--
-- TOC entry 5351 (class 0 OID 0)
-- Dependencies: 222
-- Name: TABLE shifts; Type: COMMENT; Schema: public; Owner: postgres
--

COMMENT ON TABLE public.shifts IS '班次表';


--
-- TOC entry 221 (class 1259 OID 17828)
-- Name: shifts_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.shifts_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.shifts_id_seq OWNER TO postgres;

--
-- TOC entry 5352 (class 0 OID 0)
-- Dependencies: 221
-- Name: shifts_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.shifts_id_seq OWNED BY public.shifts.id;


--
-- TOC entry 230 (class 1259 OID 17865)
-- Name: temporary_leave_applications; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.temporary_leave_applications (
    id bigint NOT NULL,
    employee_id character varying(64),
    organization_id bigint,
    shift_id bigint,
    start_at timestamp with time zone,
    end_at timestamp with time zone,
    leave_reason text,
    remark text,
    status character varying(50),
    completed_at timestamp with time zone,
    created_at timestamp with time zone,
    CONSTRAINT ck_temporary_leave_applications_status CHECK (((status IS NULL) OR ((status)::text = ANY ((ARRAY['SUBMITTED'::character varying, 'APPROVING'::character varying, 'APPROVED'::character varying, 'REJECTED'::character varying, 'CANCELLED'::character varying, 'EFFECTIVE'::character varying, 'COMPLETED'::character varying, 'EXPIRED'::character varying])::text[]))))
);


ALTER TABLE public.temporary_leave_applications OWNER TO postgres;

--
-- TOC entry 5353 (class 0 OID 0)
-- Dependencies: 230
-- Name: TABLE temporary_leave_applications; Type: COMMENT; Schema: public; Owner: postgres
--

COMMENT ON TABLE public.temporary_leave_applications IS '离岗申请';


--
-- TOC entry 229 (class 1259 OID 17864)
-- Name: temporary_leave_applications_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.temporary_leave_applications_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.temporary_leave_applications_id_seq OWNER TO postgres;

--
-- TOC entry 5354 (class 0 OID 0)
-- Dependencies: 229
-- Name: temporary_leave_applications_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.temporary_leave_applications_id_seq OWNED BY public.temporary_leave_applications.id;


--
-- TOC entry 240 (class 1259 OID 17915)
-- Name: temporary_qc_exemption_list; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.temporary_qc_exemption_list (
    id bigint NOT NULL,
    shift_id bigint,
    employee_id character varying(64),
    source_effective_temporary_leave_id bigint,
    updated_at timestamp with time zone,
    work_date date NOT NULL,
    exemption_start_at timestamp with time zone NOT NULL,
    exemption_end_at timestamp with time zone NOT NULL,
    CONSTRAINT chk_temporary_qc_exemption_window CHECK ((exemption_start_at < exemption_end_at))
);


ALTER TABLE public.temporary_qc_exemption_list OWNER TO postgres;

--
-- TOC entry 5355 (class 0 OID 0)
-- Dependencies: 240
-- Name: TABLE temporary_qc_exemption_list; Type: COMMENT; Schema: public; Owner: postgres
--

COMMENT ON TABLE public.temporary_qc_exemption_list IS '离岗临时免检名单';


--
-- TOC entry 239 (class 1259 OID 17914)
-- Name: temporary_qc_exemption_list_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.temporary_qc_exemption_list_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.temporary_qc_exemption_list_id_seq OWNER TO postgres;

--
-- TOC entry 5356 (class 0 OID 0)
-- Dependencies: 239
-- Name: temporary_qc_exemption_list_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.temporary_qc_exemption_list_id_seq OWNED BY public.temporary_qc_exemption_list.id;


--
-- TOC entry 4944 (class 2604 OID 17850)
-- Name: admin_list id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.admin_list ALTER COLUMN id SET DEFAULT nextval('public.admin_list_id_seq'::regclass);


--
-- TOC entry 4956 (class 2604 OID 17955)
-- Name: approval_task_queue id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.approval_task_queue ALTER COLUMN id SET DEFAULT nextval('public.approval_task_queue_id_seq'::regclass);


--
-- TOC entry 4952 (class 2604 OID 17926)
-- Name: audit_results id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.audit_results ALTER COLUMN id SET DEFAULT nextval('public.audit_results_id_seq'::regclass);


--
-- TOC entry 4957 (class 2604 OID 17965)
-- Name: audit_task_queue id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.audit_task_queue ALTER COLUMN id SET DEFAULT nextval('public.audit_task_queue_id_seq'::regclass);


--
-- TOC entry 4947 (class 2604 OID 17878)
-- Name: clock_records id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.clock_records ALTER COLUMN id SET DEFAULT nextval('public.clock_records_id_seq'::regclass);


--
-- TOC entry 4948 (class 2604 OID 17888)
-- Name: effective_leave_days id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.effective_leave_days ALTER COLUMN id SET DEFAULT nextval('public.effective_leave_days_id_seq'::regclass);


--
-- TOC entry 4949 (class 2604 OID 17898)
-- Name: effective_temporary_leaves id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.effective_temporary_leaves ALTER COLUMN id SET DEFAULT nextval('public.effective_temporary_leaves_id_seq'::regclass);


--
-- TOC entry 4954 (class 2604 OID 17944)
-- Name: event_logs id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.event_logs ALTER COLUMN id SET DEFAULT nextval('public.event_logs_id_seq'::regclass);


--
-- TOC entry 4945 (class 2604 OID 17858)
-- Name: leave_applications id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.leave_applications ALTER COLUMN id SET DEFAULT nextval('public.leave_applications_id_seq'::regclass);


--
-- TOC entry 4961 (class 2604 OID 17987)
-- Name: notification_queue id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.notification_queue ALTER COLUMN id SET DEFAULT nextval('public.notification_queue_id_seq'::regclass);


--
-- TOC entry 4941 (class 2604 OID 17824)
-- Name: organizations id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.organizations ALTER COLUMN id SET DEFAULT nextval('public.organizations_id_seq'::regclass);


--
-- TOC entry 4950 (class 2604 OID 17908)
-- Name: qc_exemption_fixed_list id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.qc_exemption_fixed_list ALTER COLUMN id SET DEFAULT nextval('public.qc_exemption_fixed_list_id_seq'::regclass);


--
-- TOC entry 4953 (class 2604 OID 17934)
-- Name: qc_results id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.qc_results ALTER COLUMN id SET DEFAULT nextval('public.qc_results_id_seq'::regclass);


--
-- TOC entry 4959 (class 2604 OID 17976)
-- Name: qc_task_queue id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.qc_task_queue ALTER COLUMN id SET DEFAULT nextval('public.qc_task_queue_id_seq'::regclass);


--
-- TOC entry 4943 (class 2604 OID 17842)
-- Name: registrations id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.registrations ALTER COLUMN id SET DEFAULT nextval('public.registrations_id_seq'::regclass);


--
-- TOC entry 4942 (class 2604 OID 17832)
-- Name: shifts id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.shifts ALTER COLUMN id SET DEFAULT nextval('public.shifts_id_seq'::regclass);


--
-- TOC entry 4946 (class 2604 OID 17868)
-- Name: temporary_leave_applications id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.temporary_leave_applications ALTER COLUMN id SET DEFAULT nextval('public.temporary_leave_applications_id_seq'::regclass);


--
-- TOC entry 4951 (class 2604 OID 17918)
-- Name: temporary_qc_exemption_list id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.temporary_qc_exemption_list ALTER COLUMN id SET DEFAULT nextval('public.temporary_qc_exemption_list_id_seq'::regclass);


--
-- TOC entry 5286 (class 0 OID 17847)
-- Dependencies: 226
-- Data for Name: admin_list; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.admin_list (id, admin_employee_id) FROM stdin;
2	72494
\.


--
-- TOC entry 5308 (class 0 OID 17952)
-- Dependencies: 248
-- Data for Name: approval_task_queue; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.approval_task_queue (id, application_type, application_id, application_submitted_at, approval_level, applicant_employee_id, approver_employee_id, task_status, approval_result, approved_at, approver_remark, task_created_at) FROM stdin;
1	LEAVE	1	2026-04-03 23:48:43.743006+08	1	7122	72494	PROCESSING	NONE	\N	\N	2026-04-03 23:48:43.743008+08
3	LEAVE	3	2026-04-05 23:26:38.415443+08	1	7122	72494	APPROVED_DONE	APPROVED	2026-04-05 23:41:23.203407+08	\N	2026-04-05 23:26:38.415446+08
4	LEAVE	4	2026-04-06 00:05:00.951206+08	1	7122	72494	APPROVED_DONE	APPROVED	2026-04-06 00:05:17.498661+08	\N	2026-04-06 00:05:00.951208+08
5	LEAVE	5	2026-04-10 18:07:26.975953+08	1	7122	72494	APPROVED_DONE	APPROVED	2026-04-10 18:07:42.34931+08	\N	2026-04-10 18:07:26.975955+08
2	LEAVE	2	2026-04-04 00:00:59.725504+08	1	72494	72494	PROCESSING	NONE	\N	\N	2026-04-04 00:00:59.725506+08
6	TEMPORARY_LEAVE	1	2026-04-11 13:46:36.407737+08	1	7122	7122	PENDING	NONE	\N	\N	2026-04-11 13:46:36.407738+08
7	TEMPORARY_LEAVE	2	2026-04-11 15:05:45.869075+08	1	7122	7122	APPROVED_DONE	APPROVED	2026-04-11 15:05:51.709042+08	\N	2026-04-11 15:05:45.869076+08
8	TEMPORARY_LEAVE	3	2026-04-11 16:27:12.655951+08	1	7122	7122	APPROVED_DONE	APPROVED	2026-04-11 16:27:18.137521+08	\N	2026-04-11 16:27:12.655952+08
9	TEMPORARY_LEAVE	4	2026-04-11 16:32:39.660374+08	1	7122	7122	APPROVED_DONE	APPROVED	2026-04-11 16:32:45.026213+08	\N	2026-04-11 16:32:39.660375+08
10	TEMPORARY_LEAVE	5	2026-04-11 16:41:07.918458+08	1	7122	7122	APPROVED_DONE	APPROVED	2026-04-11 16:41:12.256881+08	\N	2026-04-11 16:41:07.918459+08
11	TEMPORARY_LEAVE	6	2026-04-11 19:56:43.311124+08	1	7122	7122	PENDING	NONE	\N	\N	2026-04-11 19:56:43.311125+08
12	TEMPORARY_LEAVE	7	2026-04-11 19:59:26.844536+08	1	7122	7122	APPROVED_DONE	APPROVED	2026-04-11 19:59:33.939853+08	\N	2026-04-11 19:59:26.844538+08
13	TEMPORARY_LEAVE	8	2026-04-11 22:25:30.148395+08	1	7122	7122	APPROVED_DONE	APPROVED	2026-04-11 22:25:35.283795+08	\N	2026-04-11 22:25:30.148396+08
14	LEAVE	6	2026-04-12 21:56:56.572054+08	1	7122	7122	REJECTED_DONE	REJECTED	2026-04-12 21:58:01.034407+08	工作任务紧张缺乏人手，该假期不予批准	2026-04-12 21:56:56.572055+08
15	TEMPORARY_LEAVE	9	2026-04-12 22:40:34.447706+08	1	7122	7122	APPROVED_DONE	APPROVED	2026-04-12 22:41:25.891267+08	\N	2026-04-12 22:40:34.447706+08
\.


--
-- TOC entry 5302 (class 0 OID 17923)
-- Dependencies: 242
-- Data for Name: audit_results; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.audit_results (id, employee_id, shift_id, organization_id, audit_date, audit_stage, checked_at, valid_clock_time, result) FROM stdin;
27	72494	1	1	2026-04-10	CHECKOUT	2026-04-10 23:39:30.39679+08	2026-04-10 23:34:36.597175+08	NORMAL
28	56773	1	1	2026-04-10	CHECKOUT	2026-04-11 05:01:33.858514+08	\N	ABSENT
29	74114	1	2	2026-04-10	CHECKOUT	2026-04-11 05:01:34.170186+08	\N	ABSENT
30	58073	1	1	2026-04-10	CHECKOUT	2026-04-11 05:01:34.490877+08	\N	ABSENT
31	59242	1	2	2026-04-10	CHECKOUT	2026-04-11 05:01:34.684469+08	\N	ABSENT
32	72357	1	2	2026-04-10	CHECKOUT	2026-04-11 05:01:34.873163+08	\N	ABSENT
33	74168	1	3	2026-04-10	CHECKOUT	2026-04-11 05:01:35.074294+08	\N	ABSENT
34	74306	1	1	2026-04-10	CHECKOUT	2026-04-11 05:01:35.403841+08	\N	ABSENT
35	74314	1	1	2026-04-10	CHECKOUT	2026-04-11 05:01:35.927552+08	\N	ABSENT
36	74322	1	1	2026-04-10	CHECKOUT	2026-04-11 05:01:36.115643+08	\N	ABSENT
37	4257	1	2	2026-04-10	CHECKOUT	2026-04-11 05:01:36.408547+08	\N	ABSENT
38	16908	1	2	2026-04-10	CHECKOUT	2026-04-11 05:01:36.716014+08	\N	ABSENT
39	17025	1	1	2026-04-10	CHECKOUT	2026-04-11 05:01:36.910668+08	\N	ABSENT
40	29337	1	1	2026-04-10	CHECKOUT	2026-04-11 05:01:37.111584+08	\N	ABSENT
41	31088	1	3	2026-04-10	CHECKOUT	2026-04-11 05:01:37.301963+08	\N	ABSENT
42	51761	1	0	2026-04-10	CHECKOUT	2026-04-11 05:01:37.626429+08	\N	ABSENT
43	51964	0	0	2026-04-10	CHECKOUT	2026-04-11 05:01:37.921125+08	\N	ABSENT
44	55516	1	2	2026-04-10	CHECKOUT	2026-04-11 05:01:38.220453+08	\N	ABSENT
45	56753	1	1	2026-04-10	CHECKOUT	2026-04-11 05:01:38.650745+08	\N	ABSENT
46	56759	1	3	2026-04-10	CHECKOUT	2026-04-11 05:01:38.855629+08	\N	ABSENT
47	51761	1	0	2026-04-11	CHECKIN	2026-04-11 11:47:46.728826+08	2026-04-11 11:47:33.051847+08	NORMAL
48	72494	1	1	2026-04-11	CHECKIN	2026-04-11 13:11:45.821509+08	2026-04-11 13:09:42.815619+08	NORMAL
49	17025	1	1	2026-04-11	CHECKIN	2026-04-11 13:24:19.048708+08	2026-04-11 13:22:07.894417+08	NORMAL
50	74306	1	1	2026-04-11	CHECKIN	2026-04-11 13:24:22.20974+08	2026-04-11 13:24:08.747855+08	NORMAL
51	72357	1	2	2026-04-11	CHECKIN	2026-04-11 13:27:03.966198+08	2026-04-11 13:26:20.812231+08	NORMAL
52	56753	1	1	2026-04-11	CHECKIN	2026-04-11 13:32:06.796189+08	2026-04-11 13:31:10.329218+08	NORMAL
53	4257	1	2	2026-04-11	CHECKIN	2026-04-11 13:34:27.414174+08	2026-04-11 13:33:44.882989+08	NORMAL
54	56773	1	1	2026-04-11	CHECKIN	2026-04-11 13:39:32.935008+08	2026-04-11 13:39:03.318455+08	NORMAL
55	29337	1	1	2026-04-11	CHECKIN	2026-04-11 13:44:35.520422+08	2026-04-11 13:40:58.109409+08	NORMAL
56	58073	1	1	2026-04-11	CHECKIN	2026-04-11 13:44:36.280379+08	2026-04-11 13:42:19.244462+08	NORMAL
57	74168	1	3	2026-04-11	CHECKIN	2026-04-11 13:44:36.668479+08	2026-04-11 13:43:28.288054+08	NORMAL
58	74314	1	1	2026-04-11	CHECKIN	2026-04-11 13:44:37.380382+08	2026-04-11 13:43:55.201618+08	NORMAL
59	55516	1	2	2026-04-11	CHECKIN	2026-04-11 13:49:38.41556+08	2026-04-11 13:49:02.565968+08	NORMAL
60	59242	1	2	2026-04-11	CHECKIN	2026-04-11 13:49:39.036512+08	2026-04-11 13:47:23.22886+08	NORMAL
61	74322	1	1	2026-04-11	CHECKIN	2026-04-11 13:50:41.043304+08	2026-04-11 13:50:39.13177+08	NORMAL
62	74114	1	2	2026-04-11	CHECKIN	2026-04-11 13:54:41.896186+08	2026-04-11 13:53:58.986435+08	NORMAL
63	51964	0	0	2026-04-11	CHECKIN	2026-04-11 19:51:14.938576+08	\N	ABSENT
64	7122	0	0	2026-04-11	CHECKIN	2026-04-11 19:51:15.127085+08	\N	ABSENT
65	56759	1	3	2026-04-11	CHECKIN	2026-04-11 20:02:46.078594+08	\N	ABSENT
66	31088	1	3	2026-04-11	CHECKIN	2026-04-11 20:02:46.276031+08	\N	ABSENT
67	16908	1	2	2026-04-11	CHECKIN	2026-04-11 20:02:46.564729+08	\N	ABSENT
68	72494	1	1	2026-04-11	CHECKOUT	2026-04-11 23:01:37.557548+08	2026-04-11 23:01:36.735425+08	NORMAL
69	55516	1	2	2026-04-11	CHECKOUT	2026-04-11 23:05:13.25817+08	2026-04-11 23:03:19.111731+08	NORMAL
70	56773	1	1	2026-04-11	CHECKOUT	2026-04-11 23:05:14.059611+08	2026-04-11 23:02:38.828435+08	NORMAL
71	58073	1	1	2026-04-11	CHECKOUT	2026-04-11 23:05:14.260419+08	2026-04-11 23:04:48.768+08	NORMAL
72	72357	1	2	2026-04-11	CHECKOUT	2026-04-11 23:05:14.863474+08	2026-04-11 23:04:18.26972+08	NORMAL
73	74168	1	3	2026-04-11	CHECKOUT	2026-04-11 23:05:15.577293+08	2026-04-11 23:04:37.146695+08	NORMAL
74	74314	1	1	2026-04-11	CHECKOUT	2026-04-11 23:05:16.172055+08	2026-04-11 23:02:12.27486+08	NORMAL
75	29337	1	1	2026-04-11	CHECKOUT	2026-04-11 23:05:17.191969+08	2026-04-11 23:02:26.198015+08	NORMAL
76	59242	1	2	2026-04-11	CHECKOUT	2026-04-11 23:06:41.297903+08	2026-04-11 23:06:11.651236+08	NORMAL
77	74114	1	2	2026-04-11	CHECKOUT	2026-04-11 23:06:41.581567+08	2026-04-11 23:06:15.116718+08	NORMAL
78	17025	1	1	2026-04-11	CHECKOUT	2026-04-11 23:06:42.837632+08	2026-04-11 23:05:36.65755+08	NORMAL
79	56753	1	1	2026-04-11	CHECKOUT	2026-04-11 23:10:19.784593+08	2026-04-11 23:07:51.067797+08	NORMAL
80	4257	1	2	2026-04-11	CHECKOUT	2026-04-11 23:10:20.73016+08	2026-04-11 23:06:46.639535+08	NORMAL
81	7122	0	0	2026-04-11	CHECKOUT	2026-04-12 02:14:51.440305+08	\N	ABSENT
82	51761	0	0	2026-04-11	CHECKOUT	2026-04-12 02:14:51.635655+08	\N	ABSENT
83	51964	0	0	2026-04-11	CHECKOUT	2026-04-12 02:14:51.944375+08	\N	ABSENT
84	7122	0	0	2026-04-12	CHECKIN	2026-04-12 02:33:16.277782+08	2026-04-12 02:32:25.328037+08	NORMAL
85	31088	1	3	2026-04-11	CHECKOUT	2026-04-12 05:03:10.165749+08	\N	ABSENT
86	56759	1	3	2026-04-11	CHECKOUT	2026-04-12 05:03:10.478236+08	\N	ABSENT
87	74306	1	1	2026-04-11	CHECKOUT	2026-04-12 05:03:10.899192+08	\N	ABSENT
88	74322	1	1	2026-04-11	CHECKOUT	2026-04-12 05:03:11.194591+08	\N	ABSENT
89	16908	1	2	2026-04-11	CHECKOUT	2026-04-12 05:03:11.497654+08	\N	ABSENT
90	51761	0	0	2026-04-12	CHECKIN	2026-04-12 08:13:57.425554+08	\N	ABSENT
91	51964	0	0	2026-04-12	CHECKIN	2026-04-12 08:13:57.712844+08	\N	ABSENT
92	72494	1	1	2026-04-12	CHECKIN	2026-04-12 12:53:14.062826+08	2026-04-12 12:49:58.296105+08	NORMAL
93	17025	1	1	2026-04-12	CHECKIN	2026-04-12 13:28:57.855968+08	2026-04-12 13:25:27.378269+08	NORMAL
94	4257	1	2	2026-04-12	CHECKIN	2026-04-12 13:34:03.508064+08	2026-04-12 13:32:50.469086+08	NORMAL
95	56753	1	1	2026-04-12	CHECKIN	2026-04-12 13:34:04.986061+08	2026-04-12 13:32:32.894783+08	NORMAL
96	56773	1	1	2026-04-12	CHECKIN	2026-04-12 13:34:05.730689+08	2026-04-12 13:33:10.350949+08	NORMAL
97	74114	1	2	2026-04-12	CHECKIN	2026-04-12 13:39:12.054733+08	2026-04-12 13:36:57.070498+08	NORMAL
98	29337	1	1	2026-04-12	CHECKIN	2026-04-12 13:44:14.802388+08	2026-04-12 13:42:54.092815+08	NORMAL
99	72357	1	2	2026-04-12	CHECKIN	2026-04-12 13:44:16.482469+08	2026-04-12 13:43:54.423602+08	NORMAL
100	74306	1	1	2026-04-12	CHECKIN	2026-04-12 13:44:16.958861+08	2026-04-12 13:43:35.706494+08	NORMAL
101	55516	1	2	2026-04-12	CHECKIN	2026-04-12 13:49:19.954865+08	2026-04-12 13:48:43.306996+08	NORMAL
102	56759	1	3	2026-04-12	CHECKIN	2026-04-12 13:49:20.254107+08	2026-04-12 13:47:07.703564+08	NORMAL
103	58073	1	1	2026-04-12	CHECKIN	2026-04-12 13:49:20.57828+08	2026-04-12 13:47:49.242511+08	NORMAL
104	59242	1	2	2026-04-12	CHECKIN	2026-04-12 13:49:20.890318+08	2026-04-12 13:46:53.039117+08	NORMAL
105	74168	1	3	2026-04-12	CHECKIN	2026-04-12 13:49:21.202797+08	2026-04-12 13:46:36.269862+08	NORMAL
106	74314	1	1	2026-04-12	CHECKIN	2026-04-12 13:49:21.372642+08	2026-04-12 13:48:18.632596+08	NORMAL
107	16908	1	2	2026-04-12	CHECKIN	2026-04-12 13:54:24.234747+08	2026-04-12 13:52:08.601506+08	NORMAL
108	31088	1	3	2026-04-12	CHECKIN	2026-04-12 13:54:24.655916+08	2026-04-12 13:50:26.659587+08	NORMAL
109	74322	1	1	2026-04-12	CHECKIN	2026-04-12 13:54:24.977303+08	2026-04-12 13:52:26.880663+08	NORMAL
110	7122	0	0	2026-04-12	CHECKOUT	2026-04-12 19:01:33.947976+08	\N	ABSENT
111	51761	0	0	2026-04-12	CHECKOUT	2026-04-12 19:01:34.274413+08	\N	ABSENT
112	51964	0	0	2026-04-12	CHECKOUT	2026-04-12 19:01:34.474787+08	\N	ABSENT
113	17025	1	1	2026-04-12	CHECKOUT	2026-04-12 23:05:14.912315+08	2026-04-12 23:01:33.445664+08	NORMAL
114	55516	1	2	2026-04-12	CHECKOUT	2026-04-12 23:05:15.800787+08	2026-04-12 23:02:03.834296+08	NORMAL
115	56759	1	3	2026-04-12	CHECKOUT	2026-04-12 23:05:16.274957+08	2026-04-12 23:02:54.533833+08	NORMAL
116	56773	1	1	2026-04-12	CHECKOUT	2026-04-12 23:05:16.569762+08	2026-04-12 23:02:11.2222+08	NORMAL
117	58073	1	1	2026-04-12	CHECKOUT	2026-04-12 23:05:16.753695+08	2026-04-12 23:02:56.035369+08	NORMAL
118	59242	1	2	2026-04-12	CHECKOUT	2026-04-12 23:05:16.938309+08	2026-04-12 23:03:30.571479+08	NORMAL
119	72357	1	2	2026-04-12	CHECKOUT	2026-04-12 23:05:17.242824+08	2026-04-12 23:04:52.292537+08	NORMAL
120	16908	1	2	2026-04-12	CHECKOUT	2026-04-12 23:10:20.197838+08	2026-04-12 23:06:29.070705+08	NORMAL
121	31088	1	3	2026-04-12	CHECKOUT	2026-04-12 23:10:20.931598+08	2026-04-12 23:05:48.433534+08	NORMAL
122	74114	1	2	2026-04-12	CHECKOUT	2026-04-12 23:10:21.428119+08	2026-04-12 23:07:01.882499+08	NORMAL
123	4257	1	2	2026-04-12	CHECKOUT	2026-04-12 23:15:24.163382+08	2026-04-12 23:11:35.507657+08	NORMAL
124	29337	1	1	2026-04-12	CHECKOUT	2026-04-12 23:15:24.444287+08	2026-04-12 23:14:31.736325+08	NORMAL
125	56753	1	1	2026-04-12	CHECKOUT	2026-04-12 23:15:24.633959+08	2026-04-12 23:12:29.542171+08	NORMAL
126	74168	1	3	2026-04-12	CHECKOUT	2026-04-12 23:15:24.930264+08	2026-04-12 23:12:37.634901+08	NORMAL
127	74306	1	1	2026-04-12	CHECKOUT	2026-04-12 23:15:25.105941+08	2026-04-12 23:13:28.252398+08	NORMAL
128	74314	1	1	2026-04-12	CHECKOUT	2026-04-12 23:30:31.860557+08	2026-04-12 23:27:17.757313+08	NORMAL
129	72494	1	1	2026-04-12	CHECKOUT	2026-04-12 23:35:33.869374+08	2026-04-12 23:32:07.073555+08	NORMAL
130	74322	1	1	2026-04-12	CHECKOUT	2026-04-12 23:50:39.064017+08	2026-04-12 23:47:11.611377+08	NORMAL
131	74314	1	1	2026-04-13	CHECKIN	2026-04-13 13:21:32.491375+08	2026-04-13 13:16:51.299017+08	NORMAL
132	74306	1	1	2026-04-13	CHECKIN	2026-04-13 13:26:37.793546+08	2026-04-13 13:22:29.840893+08	NORMAL
133	72494	1	1	2026-04-13	CHECKIN	2026-04-13 13:36:45.29944+08	2026-04-13 13:33:13.940066+08	NORMAL
134	4257	1	2	2026-04-13	CHECKIN	2026-04-13 13:36:45.472513+08	2026-04-13 13:33:34.832275+08	NORMAL
135	17025	1	1	2026-04-13	CHECKIN	2026-04-13 13:36:46.071305+08	2026-04-13 13:35:47.425418+08	NORMAL
136	56773	1	1	2026-04-13	CHECKIN	2026-04-13 13:36:47.552661+08	2026-04-13 13:35:13.22445+08	NORMAL
137	72357	1	2	2026-04-13	CHECKIN	2026-04-13 13:41:52.495803+08	2026-04-13 13:41:43.389437+08	NORMAL
138	29337	1	1	2026-04-13	CHECKIN	2026-04-13 13:46:54.696019+08	2026-04-13 13:43:02.115242+08	NORMAL
139	58073	1	1	2026-04-13	CHECKIN	2026-04-13 13:46:55.751254+08	2026-04-13 13:43:56.868152+08	NORMAL
140	16908	1	2	2026-04-13	CHECKIN	2026-04-13 13:51:58.542594+08	2026-04-13 13:51:39.582652+08	NORMAL
141	31088	1	3	2026-04-13	CHECKIN	2026-04-13 13:51:58.711456+08	2026-04-13 13:50:09.007186+08	NORMAL
142	55516	1	2	2026-04-13	CHECKIN	2026-04-13 13:51:58.997462+08	2026-04-13 13:49:41.392514+08	NORMAL
143	56753	1	1	2026-04-13	CHECKIN	2026-04-13 13:51:59.1768+08	2026-04-13 13:47:23.299253+08	NORMAL
144	59242	1	2	2026-04-13	CHECKIN	2026-04-13 13:51:59.564457+08	2026-04-13 13:51:43.919303+08	NORMAL
145	74114	1	2	2026-04-13	CHECKIN	2026-04-13 13:51:59.740271+08	2026-04-13 13:47:16.97253+08	NORMAL
146	74322	1	1	2026-04-13	CHECKIN	2026-04-13 13:52:00.093713+08	2026-04-13 13:49:56.445989+08	NORMAL
147	56759	1	3	2026-04-13	CHECKIN	2026-04-13 13:57:01.605171+08	2026-04-13 13:53:05.998268+08	NORMAL
148	74168	1	3	2026-04-13	CHECKIN	2026-04-13 14:02:11.474453+08	2026-04-13 13:57:45.83834+08	NORMAL
149	7122	0	0	2026-04-13	CHECKIN	2026-04-13 20:02:49.022912+08	\N	ABSENT
150	51761	0	0	2026-04-13	CHECKIN	2026-04-13 20:02:49.303727+08	\N	ABSENT
151	51964	0	0	2026-04-13	CHECKIN	2026-04-13 20:02:49.60479+08	\N	ABSENT
152	4257	1	2	2026-04-13	CHECKOUT	2026-04-13 23:03:33.24666+08	2026-04-13 23:01:29.269443+08	NORMAL
153	16908	1	2	2026-04-13	CHECKOUT	2026-04-13 23:03:33.543014+08	2026-04-13 23:02:38.825783+08	NORMAL
154	17025	1	1	2026-04-13	CHECKOUT	2026-04-13 23:03:33.721578+08	2026-04-13 23:02:03.570423+08	NORMAL
155	29337	1	1	2026-04-13	CHECKOUT	2026-04-13 23:03:33.907434+08	2026-04-13 23:01:36.650513+08	NORMAL
156	55516	1	2	2026-04-13	CHECKOUT	2026-04-13 23:03:34.29517+08	2026-04-13 23:01:23.403488+08	NORMAL
157	58073	1	1	2026-04-13	CHECKOUT	2026-04-13 23:03:35.071979+08	2026-04-13 23:03:04.982096+08	NORMAL
158	59242	1	2	2026-04-13	CHECKOUT	2026-04-13 23:03:35.354895+08	2026-04-13 23:02:33.924779+08	NORMAL
159	74314	1	1	2026-04-13	CHECKOUT	2026-04-13 23:03:37.173142+08	2026-04-13 23:02:17.115077+08	NORMAL
160	31088	1	3	2026-04-13	CHECKOUT	2026-04-13 23:08:40.103152+08	2026-04-13 23:03:46.923367+08	NORMAL
161	56753	1	1	2026-04-13	CHECKOUT	2026-04-13 23:08:40.389846+08	2026-04-13 23:08:33.711571+08	NORMAL
162	56759	1	3	2026-04-13	CHECKOUT	2026-04-13 23:08:40.699502+08	2026-04-13 23:06:18.311818+08	NORMAL
163	72357	1	2	2026-04-13	CHECKOUT	2026-04-13 23:08:41.089161+08	2026-04-13 23:05:18.36799+08	NORMAL
164	74114	1	2	2026-04-13	CHECKOUT	2026-04-13 23:13:44.838826+08	2026-04-13 23:11:56.223976+08	NORMAL
165	56773	1	1	2026-04-13	CHECKOUT	2026-04-13 23:18:48.73536+08	2026-04-13 23:14:17.313395+08	NORMAL
166	74168	1	3	2026-04-13	CHECKOUT	2026-04-13 23:18:49.037721+08	2026-04-13 23:16:25.682754+08	NORMAL
167	72494	1	1	2026-04-13	CHECKOUT	2026-04-13 23:28:55.26681+08	2026-04-13 23:24:36.921721+08	NORMAL
168	74306	1	1	2026-04-13	CHECKOUT	2026-04-13 23:33:58.484589+08	2026-04-13 23:32:41.429708+08	NORMAL
169	74322	1	1	2026-04-13	CHECKOUT	2026-04-13 23:49:07.442212+08	2026-04-13 23:44:43.583419+08	NORMAL
170	7122	0	0	2026-04-13	CHECKOUT	2026-04-14 05:04:27.830219+08	\N	ABSENT
171	51761	0	0	2026-04-13	CHECKOUT	2026-04-14 05:04:28.043549+08	\N	ABSENT
172	51964	0	0	2026-04-13	CHECKOUT	2026-04-14 05:04:28.362382+08	\N	ABSENT
173	29337	1	1	2026-04-14	CHECKIN	2026-04-14 13:32:38.611017+08	2026-04-14 13:30:32.198312+08	NORMAL
174	74306	1	1	2026-04-14	CHECKIN	2026-04-14 13:32:40.224292+08	2026-04-14 13:31:29.357944+08	NORMAL
175	4257	1	2	2026-04-14	CHECKIN	2026-04-14 13:37:45.365251+08	2026-04-14 13:34:25.450191+08	NORMAL
176	56773	1	1	2026-04-14	CHECKIN	2026-04-14 13:37:46.360625+08	2026-04-14 13:35:32.326157+08	NORMAL
177	74168	1	3	2026-04-14	CHECKIN	2026-04-14 13:37:47.484175+08	2026-04-14 13:35:56.567034+08	NORMAL
178	17025	1	1	2026-04-14	CHECKIN	2026-04-14 13:47:53.527216+08	2026-04-14 13:47:30.740555+08	NORMAL
179	56759	1	3	2026-04-14	CHECKIN	2026-04-14 13:47:56.197453+08	2026-04-14 13:45:52.586892+08	NORMAL
180	16908	1	2	2026-04-14	CHECKIN	2026-04-14 13:52:59.381791+08	2026-04-14 13:51:27.420219+08	NORMAL
181	31088	1	3	2026-04-14	CHECKIN	2026-04-14 13:52:59.779974+08	2026-04-14 13:50:04.858779+08	NORMAL
182	55516	1	2	2026-04-14	CHECKIN	2026-04-14 13:52:59.974251+08	2026-04-14 13:48:57.89531+08	NORMAL
183	56753	1	1	2026-04-14	CHECKIN	2026-04-14 13:53:00.168977+08	2026-04-14 13:51:14.320836+08	NORMAL
184	58073	1	1	2026-04-14	CHECKIN	2026-04-14 13:53:00.361779+08	2026-04-14 13:48:00.953518+08	NORMAL
185	72494	1	1	2026-04-14	CHECKIN	2026-04-14 13:58:04.544504+08	2026-04-14 13:53:19.934136+08	NORMAL
186	74114	1	2	2026-04-14	CHECKIN	2026-04-14 14:03:14.776279+08	2026-04-14 13:59:34.67675+08	NORMAL
187	7122	0	0	2026-04-14	CHECKIN	2026-04-14 20:03:32.749918+08	\N	ABSENT
188	51964	0	0	2026-04-14	CHECKIN	2026-04-14 20:03:32.937615+08	\N	ABSENT
189	51761	0	0	2026-04-14	CHECKIN	2026-04-14 20:03:33.227982+08	\N	ABSENT
190	59242	1	2	2026-04-14	CHECKIN	2026-04-14 20:03:33.416976+08	\N	ABSENT
191	72357	1	2	2026-04-14	CHECKIN	2026-04-14 20:03:33.704417+08	\N	ABSENT
192	74314	1	1	2026-04-14	CHECKIN	2026-04-14 20:03:33.999467+08	\N	ABSENT
193	74322	1	1	2026-04-14	CHECKIN	2026-04-14 20:03:34.205032+08	\N	ABSENT
194	16908	1	2	2026-04-14	CHECKOUT	2026-04-14 23:03:56.400678+08	2026-04-14 23:03:41.429262+08	NORMAL
195	17025	1	1	2026-04-14	CHECKOUT	2026-04-14 23:03:56.646735+08	2026-04-14 23:02:08.56757+08	NORMAL
196	55516	1	2	2026-04-14	CHECKOUT	2026-04-14 23:03:57.700561+08	2026-04-14 23:01:32.343803+08	NORMAL
197	56773	1	1	2026-04-14	CHECKOUT	2026-04-14 23:03:58.867789+08	2026-04-14 23:02:38.087443+08	NORMAL
198	74168	1	3	2026-04-14	CHECKOUT	2026-04-14 23:04:00.529325+08	2026-04-14 23:03:05.037688+08	NORMAL
199	4257	1	2	2026-04-14	CHECKOUT	2026-04-14 23:09:04.960931+08	2026-04-14 23:05:41.532624+08	NORMAL
200	29337	1	1	2026-04-14	CHECKOUT	2026-04-14 23:09:05.199209+08	2026-04-14 23:07:03.020939+08	NORMAL
201	31088	1	3	2026-04-14	CHECKOUT	2026-04-14 23:09:05.440239+08	2026-04-14 23:06:47.740684+08	NORMAL
202	56759	1	3	2026-04-14	CHECKOUT	2026-04-14 23:09:06.119198+08	2026-04-14 23:08:31.195927+08	NORMAL
203	58073	1	1	2026-04-14	CHECKOUT	2026-04-14 23:09:06.360669+08	2026-04-14 23:04:28.752768+08	NORMAL
204	74114	1	2	2026-04-14	CHECKOUT	2026-04-14 23:09:07.272482+08	2026-04-14 23:05:55.058309+08	NORMAL
205	56753	1	1	2026-04-14	CHECKOUT	2026-04-14 23:19:17.948211+08	2026-04-14 23:16:28.815152+08	NORMAL
206	72494	1	1	2026-04-14	CHECKOUT	2026-04-15 00:05:07.871651+08	2026-04-15 00:01:04.324026+08	NORMAL
207	51964	0	0	2026-04-14	CHECKOUT	2026-04-19 14:32:36.65081+08	\N	ABSENT
208	51761	0	0	2026-04-14	CHECKOUT	2026-04-19 14:32:36.950183+08	\N	ABSENT
209	7122	0	0	2026-04-14	CHECKOUT	2026-04-19 14:32:37.241706+08	\N	ABSENT
210	74322	1	1	2026-04-14	CHECKOUT	2026-04-19 14:32:37.442497+08	\N	ABSENT
211	59242	1	2	2026-04-14	CHECKOUT	2026-04-19 14:32:37.641833+08	\N	ABSENT
212	72357	1	2	2026-04-14	CHECKOUT	2026-04-19 14:32:37.95369+08	\N	ABSENT
213	74306	1	1	2026-04-14	CHECKOUT	2026-04-19 14:32:38.147597+08	\N	ABSENT
214	74314	1	1	2026-04-14	CHECKOUT	2026-04-19 14:32:38.325728+08	\N	ABSENT
215	58073	1	1	2026-04-19	CHECKIN	2026-04-19 14:37:45.074191+08	2026-04-19 14:32:48.358279+08	NORMAL
216	59242	1	2	2026-04-19	CHECKIN	2026-04-19 14:37:45.261921+08	2026-04-19 14:32:48.481211+08	NORMAL
217	72357	1	2	2026-04-19	CHECKIN	2026-04-19 14:37:45.545918+08	2026-04-19 14:32:47.519718+08	NORMAL
218	74114	1	2	2026-04-19	CHECKIN	2026-04-19 14:37:45.842873+08	2026-04-19 14:32:47.302158+08	NORMAL
219	74168	1	3	2026-04-19	CHECKIN	2026-04-19 14:37:46.146952+08	2026-04-19 14:32:47.41323+08	NORMAL
220	74306	1	1	2026-04-19	CHECKIN	2026-04-19 14:37:46.426978+08	2026-04-19 14:32:48.051211+08	NORMAL
221	74314	1	1	2026-04-19	CHECKIN	2026-04-19 14:37:46.724547+08	2026-04-19 14:32:46.011689+08	NORMAL
222	74322	1	1	2026-04-19	CHECKIN	2026-04-19 14:37:47.039738+08	2026-04-19 14:32:47.836358+08	NORMAL
223	72494	1	1	2026-04-19	CHECKIN	2026-04-19 14:37:47.233946+08	2026-04-19 14:32:46.113344+08	NORMAL
224	4257	1	2	2026-04-19	CHECKIN	2026-04-19 14:37:47.54367+08	2026-04-19 14:32:47.618568+08	NORMAL
225	16908	1	2	2026-04-19	CHECKIN	2026-04-19 14:37:47.850535+08	2026-04-19 14:32:50.18869+08	NORMAL
226	17025	1	1	2026-04-19	CHECKIN	2026-04-19 14:37:48.027352+08	2026-04-19 14:32:47.944685+08	NORMAL
227	29337	1	1	2026-04-19	CHECKIN	2026-04-19 14:37:48.228602+08	2026-04-19 14:32:46.655419+08	NORMAL
228	31088	1	3	2026-04-19	CHECKIN	2026-04-19 14:37:48.435693+08	2026-04-19 14:32:47.017078+08	NORMAL
229	55516	1	2	2026-04-19	CHECKIN	2026-04-19 14:37:48.723+08	2026-04-19 14:32:46.917432+08	NORMAL
230	56753	1	1	2026-04-19	CHECKIN	2026-04-19 14:37:48.907155+08	2026-04-19 14:32:48.264402+08	NORMAL
231	56759	1	3	2026-04-19	CHECKIN	2026-04-19 14:37:49.202807+08	2026-04-19 14:32:49.459548+08	NORMAL
232	56773	1	1	2026-04-19	CHECKIN	2026-04-19 14:37:49.389848+08	2026-04-19 14:32:49.240318+08	NORMAL
233	7122	0	0	2026-04-19	CHECKIN	2026-04-19 20:03:06.640191+08	\N	ABSENT
234	51964	0	0	2026-04-19	CHECKIN	2026-04-19 20:03:06.835487+08	\N	ABSENT
235	51761	0	0	2026-04-19	CHECKIN	2026-04-19 20:03:07.035671+08	\N	ABSENT
236	17025	1	1	2026-04-19	CHECKOUT	2026-04-19 23:03:19.495631+08	2026-04-19 23:01:10.725452+08	NORMAL
237	31088	1	3	2026-04-19	CHECKOUT	2026-04-19 23:03:20.28058+08	2026-04-19 23:02:50.930837+08	NORMAL
238	55516	1	2	2026-04-19	CHECKOUT	2026-04-19 23:03:20.812601+08	2026-04-19 23:02:34.547581+08	NORMAL
239	56773	1	1	2026-04-19	CHECKOUT	2026-04-19 23:03:21.374437+08	2026-04-19 23:02:35.802614+08	NORMAL
240	72357	1	2	2026-04-19	CHECKOUT	2026-04-19 23:03:22.44063+08	2026-04-19 23:01:51.200978+08	NORMAL
241	74314	1	1	2026-04-19	CHECKOUT	2026-04-19 23:03:23.825654+08	2026-04-19 23:02:27.665596+08	NORMAL
242	29337	1	1	2026-04-19	CHECKOUT	2026-04-19 23:08:28.319711+08	2026-04-19 23:06:34.844124+08	NORMAL
243	74306	1	1	2026-04-19	CHECKOUT	2026-04-19 23:08:29.264205+08	2026-04-19 23:07:55.685786+08	NORMAL
244	56759	1	3	2026-04-19	CHECKOUT	2026-04-19 23:08:30.158828+08	2026-04-19 23:07:07.926096+08	NORMAL
245	58073	1	1	2026-04-19	CHECKOUT	2026-04-19 23:08:30.489627+08	2026-04-19 23:03:33.246766+08	NORMAL
246	59242	1	2	2026-04-19	CHECKOUT	2026-04-19 23:08:31.030298+08	2026-04-19 23:04:19.047887+08	NORMAL
247	74114	1	2	2026-04-19	CHECKOUT	2026-04-19 23:08:31.447708+08	2026-04-19 23:04:47.533943+08	NORMAL
248	4257	1	2	2026-04-19	CHECKOUT	2026-04-19 23:08:32.037331+08	2026-04-19 23:08:24.41617+08	NORMAL
249	74168	1	3	2026-04-19	CHECKOUT	2026-04-19 23:18:41.711149+08	2026-04-19 23:14:24.713901+08	NORMAL
250	16908	1	2	2026-04-19	CHECKOUT	2026-04-19 23:18:41.948243+08	2026-04-19 23:16:45.349115+08	NORMAL
251	74322	1	1	2026-04-19	CHECKOUT	2026-04-19 23:28:49.124215+08	2026-04-19 23:28:29.152277+08	NORMAL
252	7122	0	0	2026-04-19	CHECKOUT	2026-04-30 19:08:55.657862+08	\N	ABSENT
253	51761	0	0	2026-04-19	CHECKOUT	2026-04-30 19:08:55.970296+08	\N	ABSENT
254	51964	0	0	2026-04-19	CHECKOUT	2026-04-30 19:08:56.265021+08	\N	ABSENT
255	56753	1	1	2026-04-19	CHECKOUT	2026-04-30 19:08:56.559188+08	\N	ABSENT
256	72494	1	1	2026-04-19	CHECKOUT	2026-04-30 19:08:56.873899+08	2026-04-20 00:46:05.789216+08	NORMAL
257	51761	0	0	2026-04-30	CHECKIN	2026-04-30 20:00:08.640212+08	\N	ABSENT
258	7122	0	0	2026-04-30	CHECKIN	2026-04-30 20:00:08.845472+08	\N	ABSENT
259	51964	0	0	2026-04-30	CHECKIN	2026-04-30 20:00:09.045129+08	\N	ABSENT
260	16908	1	2	2026-04-30	CHECKIN	2026-04-30 20:00:09.550317+08	\N	ABSENT
261	17025	1	1	2026-04-30	CHECKIN	2026-04-30 20:00:09.855579+08	\N	ABSENT
262	29337	1	1	2026-04-30	CHECKIN	2026-04-30 20:00:10.267479+08	\N	ABSENT
263	31088	1	3	2026-04-30	CHECKIN	2026-04-30 20:00:10.444859+08	\N	ABSENT
264	4257	1	2	2026-04-30	CHECKIN	2026-04-30 20:00:10.863218+08	\N	ABSENT
265	72494	1	1	2026-04-30	CHECKIN	2026-04-30 20:00:11.170901+08	\N	ABSENT
266	74306	1	1	2026-04-30	CHECKIN	2026-04-30 20:00:11.452608+08	\N	ABSENT
267	74168	1	3	2026-04-30	CHECKIN	2026-04-30 20:00:11.641548+08	\N	ABSENT
268	74114	1	2	2026-04-30	CHECKIN	2026-04-30 20:00:12.040317+08	\N	ABSENT
269	72357	1	2	2026-04-30	CHECKIN	2026-04-30 20:00:12.341905+08	\N	ABSENT
270	59242	1	2	2026-04-30	CHECKIN	2026-04-30 20:00:12.73302+08	\N	ABSENT
271	58073	1	1	2026-04-30	CHECKIN	2026-04-30 20:00:13.014122+08	\N	ABSENT
272	56773	1	1	2026-04-30	CHECKIN	2026-04-30 20:00:13.4116+08	\N	ABSENT
273	56759	1	3	2026-04-30	CHECKIN	2026-04-30 20:00:13.721719+08	\N	ABSENT
274	55516	1	2	2026-04-30	CHECKIN	2026-04-30 20:00:14.013264+08	\N	ABSENT
275	56753	1	1	2026-04-30	CHECKIN	2026-04-30 20:00:14.439559+08	\N	ABSENT
276	74322	1	1	2026-04-30	CHECKIN	2026-04-30 20:00:14.648634+08	\N	ABSENT
277	74314	1	1	2026-04-30	CHECKIN	2026-04-30 20:00:15.086021+08	\N	ABSENT
\.


--
-- TOC entry 5310 (class 0 OID 17962)
-- Dependencies: 250
-- Data for Name: audit_task_queue; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.audit_task_queue (id, log_id, audit_started_at, employee_id, target_date, audit_stage, audit_result, created_at, processed_at, retry_count, error_message, task_status) FROM stdin;
1	3	2026-04-10 20:22:34.114796+08	72494	2026-04-10	CHECKIN	ABSENT	2026-04-10 20:22:34.114796+08	2026-04-10 20:22:39.216202+08	0	\N	DONE
34	4	2026-04-10 20:22:34.198569+08	56773	2026-04-10	CHECKOUT	ABSENT	2026-04-10 20:22:34.198569+08	2026-04-11 05:01:33.858514+08	0	\N	DONE
47	60	2026-04-11 11:01:59.799246+08	72494	2026-04-11	CHECKIN	NORMAL	2026-04-11 11:01:59.799246+08	2026-04-11 13:11:45.821509+08	0	\N	DONE
22	4	2026-04-10 20:22:34.198569+08	72494	2026-04-10	CHECKOUT	NORMAL	2026-04-10 20:22:34.198569+08	2026-04-10 23:39:30.39679+08	0	\N	DONE
38	4	2026-04-10 20:22:34.198569+08	74114	2026-04-10	CHECKOUT	ABSENT	2026-04-10 20:22:34.198569+08	2026-04-11 05:01:34.170186+08	0	\N	DONE
48	60	2026-04-11 11:01:59.799246+08	4257	2026-04-11	CHECKIN	NORMAL	2026-04-11 11:01:59.799246+08	2026-04-11 13:34:27.414174+08	0	\N	DONE
35	4	2026-04-10 20:22:34.198569+08	58073	2026-04-10	CHECKOUT	ABSENT	2026-04-10 20:22:34.198569+08	2026-04-11 05:01:34.490877+08	0	\N	DONE
36	4	2026-04-10 20:22:34.198569+08	59242	2026-04-10	CHECKOUT	ABSENT	2026-04-10 20:22:34.198569+08	2026-04-11 05:01:34.684469+08	0	\N	DONE
37	4	2026-04-10 20:22:34.198569+08	72357	2026-04-10	CHECKOUT	ABSENT	2026-04-10 20:22:34.198569+08	2026-04-11 05:01:34.873163+08	0	\N	DONE
39	4	2026-04-10 20:22:34.198569+08	74168	2026-04-10	CHECKOUT	ABSENT	2026-04-10 20:22:34.198569+08	2026-04-11 05:01:35.074294+08	0	\N	DONE
40	4	2026-04-10 20:22:34.198569+08	74306	2026-04-10	CHECKOUT	ABSENT	2026-04-10 20:22:34.198569+08	2026-04-11 05:01:35.403841+08	0	\N	DONE
41	4	2026-04-10 20:22:34.198569+08	74314	2026-04-10	CHECKOUT	ABSENT	2026-04-10 20:22:34.198569+08	2026-04-11 05:01:35.927552+08	0	\N	DONE
42	4	2026-04-10 20:22:34.198569+08	74322	2026-04-10	CHECKOUT	ABSENT	2026-04-10 20:22:34.198569+08	2026-04-11 05:01:36.115643+08	0	\N	DONE
24	4	2026-04-10 20:22:34.198569+08	4257	2026-04-10	CHECKOUT	ABSENT	2026-04-10 20:22:34.198569+08	2026-04-11 05:01:36.408547+08	0	\N	DONE
25	4	2026-04-10 20:22:34.198569+08	16908	2026-04-10	CHECKOUT	ABSENT	2026-04-10 20:22:34.198569+08	2026-04-11 05:01:36.716014+08	0	\N	DONE
67	61	2026-04-11 13:45:36.4344+08	51964	2026-04-11	CHECKIN	ABSENT	2026-04-11 13:45:36.4344+08	2026-04-11 19:51:14.938576+08	0	\N	DONE
23	4	2026-04-10 20:22:34.198569+08	7122	2026-04-10	CHECKOUT	NORMAL	2026-04-10 20:22:34.198569+08	2026-04-10 21:16:53.681872+08	0	\N	DONE
26	4	2026-04-10 20:22:34.198569+08	17025	2026-04-10	CHECKOUT	ABSENT	2026-04-10 20:22:34.198569+08	2026-04-11 05:01:36.910668+08	0	\N	DONE
27	4	2026-04-10 20:22:34.198569+08	29337	2026-04-10	CHECKOUT	ABSENT	2026-04-10 20:22:34.198569+08	2026-04-11 05:01:37.111584+08	0	\N	DONE
66	61	2026-04-11 13:45:36.4344+08	7122	2026-04-11	CHECKIN	ABSENT	2026-04-11 13:45:36.4344+08	2026-04-11 19:51:15.127085+08	0	\N	DONE
28	4	2026-04-10 20:22:34.198569+08	31088	2026-04-10	CHECKOUT	ABSENT	2026-04-10 20:22:34.198569+08	2026-04-11 05:01:37.301963+08	0	\N	DONE
29	4	2026-04-10 20:22:34.198569+08	51761	2026-04-10	CHECKOUT	ABSENT	2026-04-10 20:22:34.198569+08	2026-04-11 05:01:37.626429+08	0	\N	DONE
30	4	2026-04-10 20:22:34.198569+08	51964	2026-04-10	CHECKOUT	ABSENT	2026-04-10 20:22:34.198569+08	2026-04-11 05:01:37.921125+08	0	\N	DONE
31	4	2026-04-10 20:22:34.198569+08	55516	2026-04-10	CHECKOUT	ABSENT	2026-04-10 20:22:34.198569+08	2026-04-11 05:01:38.220453+08	0	\N	DONE
32	4	2026-04-10 20:22:34.198569+08	56753	2026-04-10	CHECKOUT	ABSENT	2026-04-10 20:22:34.198569+08	2026-04-11 05:01:38.650745+08	0	\N	DONE
68	86	2026-04-11 20:02:37.525381+08	7122	2026-04-11	CHECKOUT	ABSENT	2026-04-11 20:02:37.525381+08	2026-04-12 02:14:51.440305+08	0	\N	DONE
33	4	2026-04-10 20:22:34.198569+08	56759	2026-04-10	CHECKOUT	ABSENT	2026-04-10 20:22:34.198569+08	2026-04-11 05:01:38.855629+08	0	\N	DONE
51	60	2026-04-11 11:01:59.799246+08	29337	2026-04-11	CHECKIN	NORMAL	2026-04-11 11:01:59.799246+08	2026-04-11 13:44:35.520422+08	0	\N	DONE
60	60	2026-04-11 11:01:59.799246+08	72357	2026-04-11	CHECKIN	NORMAL	2026-04-11 11:01:59.799246+08	2026-04-11 13:27:03.966198+08	0	\N	DONE
2	3	2026-04-10 20:22:34.114796+08	7122	2026-04-10	CHECKIN	ABSENT	2026-04-10 20:22:34.114796+08	2026-04-10 20:22:39.510619+08	0	\N	DONE
69	86	2026-04-11 20:02:37.525381+08	51761	2026-04-11	CHECKOUT	ABSENT	2026-04-11 20:02:37.525381+08	2026-04-12 02:14:51.635655+08	0	\N	DONE
3	3	2026-04-10 20:22:34.114796+08	4257	2026-04-10	CHECKIN	ABSENT	2026-04-10 20:22:34.114796+08	2026-04-10 20:22:39.698203+08	0	\N	DONE
4	3	2026-04-10 20:22:34.114796+08	16908	2026-04-10	CHECKIN	ABSENT	2026-04-10 20:22:34.114796+08	2026-04-10 20:22:39.879844+08	0	\N	DONE
5	3	2026-04-10 20:22:34.114796+08	17025	2026-04-10	CHECKIN	ABSENT	2026-04-10 20:22:34.114796+08	2026-04-10 20:22:40.386783+08	0	\N	DONE
6	3	2026-04-10 20:22:34.114796+08	29337	2026-04-10	CHECKIN	ABSENT	2026-04-10 20:22:34.114796+08	2026-04-10 20:22:40.681225+08	0	\N	DONE
7	3	2026-04-10 20:22:34.114796+08	31088	2026-04-10	CHECKIN	ABSENT	2026-04-10 20:22:34.114796+08	2026-04-10 20:22:40.858938+08	0	\N	DONE
8	3	2026-04-10 20:22:34.114796+08	51761	2026-04-10	CHECKIN	ABSENT	2026-04-10 20:22:34.114796+08	2026-04-10 20:22:41.152917+08	0	\N	DONE
9	3	2026-04-10 20:22:34.114796+08	51964	2026-04-10	CHECKIN	ABSENT	2026-04-10 20:22:34.114796+08	2026-04-10 20:22:41.674298+08	0	\N	DONE
58	60	2026-04-11 11:01:59.799246+08	58073	2026-04-11	CHECKIN	NORMAL	2026-04-11 11:01:59.799246+08	2026-04-11 13:44:36.280379+08	0	\N	DONE
10	3	2026-04-10 20:22:34.114796+08	55516	2026-04-10	CHECKIN	ABSENT	2026-04-10 20:22:34.114796+08	2026-04-10 20:22:41.853694+08	0	\N	DONE
11	3	2026-04-10 20:22:34.114796+08	56753	2026-04-10	CHECKIN	ABSENT	2026-04-10 20:22:34.114796+08	2026-04-10 20:22:42.242256+08	0	\N	DONE
12	3	2026-04-10 20:22:34.114796+08	56759	2026-04-10	CHECKIN	ABSENT	2026-04-10 20:22:34.114796+08	2026-04-10 20:22:42.443331+08	0	\N	DONE
13	3	2026-04-10 20:22:34.114796+08	56773	2026-04-10	CHECKIN	ABSENT	2026-04-10 20:22:34.114796+08	2026-04-10 20:22:42.621215+08	0	\N	DONE
62	60	2026-04-11 11:01:59.799246+08	74168	2026-04-11	CHECKIN	NORMAL	2026-04-11 11:01:59.799246+08	2026-04-11 13:44:36.668479+08	0	\N	DONE
14	3	2026-04-10 20:22:34.114796+08	58073	2026-04-10	CHECKIN	ABSENT	2026-04-10 20:22:34.114796+08	2026-04-10 20:22:42.801471+08	0	\N	DONE
43	12	2026-04-10 21:16:49.500067+08	72494	2026-04-09	CHECKIN	ABSENT	2026-04-10 21:16:49.500067+08	2026-04-10 21:16:56.653737+08	0	\N	DONE
15	3	2026-04-10 20:22:34.114796+08	59242	2026-04-10	CHECKIN	ABSENT	2026-04-10 20:22:34.114796+08	2026-04-10 20:22:43.00295+08	0	\N	DONE
16	3	2026-04-10 20:22:34.114796+08	72357	2026-04-10	CHECKIN	ABSENT	2026-04-10 20:22:34.114796+08	2026-04-10 20:22:43.299629+08	0	\N	DONE
17	3	2026-04-10 20:22:34.114796+08	74114	2026-04-10	CHECKIN	ABSENT	2026-04-10 20:22:34.114796+08	2026-04-10 20:22:43.610361+08	0	\N	DONE
50	60	2026-04-11 11:01:59.799246+08	17025	2026-04-11	CHECKIN	NORMAL	2026-04-11 11:01:59.799246+08	2026-04-11 13:24:19.048708+08	0	\N	DONE
18	3	2026-04-10 20:22:34.114796+08	74168	2026-04-10	CHECKIN	ABSENT	2026-04-10 20:22:34.114796+08	2026-04-10 20:22:43.795632+08	0	\N	DONE
44	12	2026-04-10 21:16:49.500067+08	7122	2026-04-09	CHECKIN	ABSENT	2026-04-10 21:16:49.500067+08	2026-04-10 21:16:56.946529+08	0	\N	DONE
19	3	2026-04-10 20:22:34.114796+08	74306	2026-04-10	CHECKIN	ABSENT	2026-04-10 20:22:34.114796+08	2026-04-10 20:22:43.995575+08	0	\N	DONE
20	3	2026-04-10 20:22:34.114796+08	74314	2026-04-10	CHECKIN	ABSENT	2026-04-10 20:22:34.114796+08	2026-04-10 20:22:44.180837+08	0	\N	DONE
21	3	2026-04-10 20:22:34.114796+08	74322	2026-04-10	CHECKIN	ABSENT	2026-04-10 20:22:34.114796+08	2026-04-10 20:22:44.374189+08	0	\N	DONE
45	13	2026-04-10 21:16:49.58959+08	72494	2026-04-09	CHECKOUT	ABSENT	2026-04-10 21:16:49.58959+08	2026-04-10 21:16:57.123845+08	0	\N	DONE
46	13	2026-04-10 21:16:49.58959+08	7122	2026-04-09	CHECKOUT	ABSENT	2026-04-10 21:16:49.58959+08	2026-04-10 21:16:57.323047+08	0	\N	DONE
53	60	2026-04-11 11:01:59.799246+08	51761	2026-04-11	CHECKIN	NORMAL	2026-04-11 11:01:59.799246+08	2026-04-11 11:47:46.728826+08	0	\N	DONE
57	60	2026-04-11 11:01:59.799246+08	56773	2026-04-11	CHECKIN	NORMAL	2026-04-11 11:01:59.799246+08	2026-04-11 13:39:32.935008+08	0	\N	DONE
54	60	2026-04-11 11:01:59.799246+08	55516	2026-04-11	CHECKIN	NORMAL	2026-04-11 11:01:59.799246+08	2026-04-11 13:49:38.41556+08	0	\N	DONE
59	60	2026-04-11 11:01:59.799246+08	59242	2026-04-11	CHECKIN	NORMAL	2026-04-11 11:01:59.799246+08	2026-04-11 13:49:39.036512+08	0	\N	DONE
63	60	2026-04-11 11:01:59.799246+08	74306	2026-04-11	CHECKIN	NORMAL	2026-04-11 11:01:59.799246+08	2026-04-11 13:24:22.20974+08	0	\N	DONE
55	60	2026-04-11 11:01:59.799246+08	56753	2026-04-11	CHECKIN	NORMAL	2026-04-11 11:01:59.799246+08	2026-04-11 13:32:06.796189+08	0	\N	DONE
65	60	2026-04-11 11:01:59.799246+08	74322	2026-04-11	CHECKIN	NORMAL	2026-04-11 11:01:59.799246+08	2026-04-11 13:50:41.043304+08	0	\N	DONE
115	121	2026-04-12 20:01:49.863666+08	16908	2026-04-12	CHECKOUT	NORMAL	2026-04-12 20:01:49.863666+08	2026-04-12 23:10:20.197838+08	0	\N	DONE
61	60	2026-04-11 11:01:59.799246+08	74114	2026-04-11	CHECKIN	NORMAL	2026-04-11 11:01:59.799246+08	2026-04-11 13:54:41.896186+08	0	\N	DONE
64	60	2026-04-11 11:01:59.799246+08	74314	2026-04-11	CHECKIN	NORMAL	2026-04-11 11:01:59.799246+08	2026-04-11 13:44:37.380382+08	0	\N	DONE
97	111	2026-04-12 11:04:31.884673+08	16908	2026-04-12	CHECKIN	NORMAL	2026-04-12 11:04:31.884673+08	2026-04-12 13:54:24.234747+08	0	\N	DONE
82	90	2026-04-11 20:02:39.385109+08	59242	2026-04-11	CHECKOUT	NORMAL	2026-04-11 20:02:39.385109+08	2026-04-11 23:06:41.297903+08	0	\N	DONE
100	111	2026-04-12 11:04:31.884673+08	31088	2026-04-12	CHECKIN	NORMAL	2026-04-12 11:04:31.884673+08	2026-04-12 13:54:24.655916+08	0	\N	DONE
84	90	2026-04-11 20:02:39.385109+08	74114	2026-04-11	CHECKOUT	NORMAL	2026-04-11 20:02:39.385109+08	2026-04-11 23:06:41.581567+08	0	\N	DONE
89	99	2026-04-12 01:58:39.747764+08	7122	2026-04-12	CHECKIN	NORMAL	2026-04-12 01:58:39.747764+08	2026-04-12 02:33:16.277782+08	0	\N	DONE
98	111	2026-04-12 11:04:31.884673+08	17025	2026-04-12	CHECKIN	NORMAL	2026-04-12 11:04:31.884673+08	2026-04-12 13:28:57.855968+08	0	\N	DONE
112	111	2026-04-12 11:04:31.884673+08	74322	2026-04-12	CHECKIN	NORMAL	2026-04-12 11:04:31.884673+08	2026-04-12 13:54:24.977303+08	0	\N	DONE
118	121	2026-04-12 20:01:49.863666+08	31088	2026-04-12	CHECKOUT	NORMAL	2026-04-12 20:01:49.863666+08	2026-04-12 23:10:20.931598+08	0	\N	DONE
76	90	2026-04-11 20:02:39.385109+08	31088	2026-04-11	CHECKOUT	ABSENT	2026-04-11 20:02:39.385109+08	2026-04-12 05:03:10.165749+08	0	\N	DONE
152	142	2026-04-13 20:02:47.309731+08	7122	2026-04-13	CHECKOUT	ABSENT	2026-04-13 20:02:47.309731+08	2026-04-14 05:04:27.830219+08	0	\N	DONE
79	90	2026-04-11 20:02:39.385109+08	56759	2026-04-11	CHECKOUT	ABSENT	2026-04-11 20:02:39.385109+08	2026-04-12 05:03:10.478236+08	0	\N	DONE
74	90	2026-04-11 20:02:39.385109+08	17025	2026-04-11	CHECKOUT	NORMAL	2026-04-11 20:02:39.385109+08	2026-04-11 23:06:42.837632+08	0	\N	DONE
86	90	2026-04-11 20:02:39.385109+08	74306	2026-04-11	CHECKOUT	ABSENT	2026-04-11 20:02:39.385109+08	2026-04-12 05:03:10.899192+08	0	\N	DONE
153	142	2026-04-13 20:02:47.309731+08	51761	2026-04-13	CHECKOUT	ABSENT	2026-04-13 20:02:47.309731+08	2026-04-14 05:04:28.043549+08	0	\N	DONE
88	90	2026-04-11 20:02:39.385109+08	74322	2026-04-11	CHECKOUT	ABSENT	2026-04-11 20:02:39.385109+08	2026-04-12 05:03:11.194591+08	0	\N	DONE
78	90	2026-04-11 20:02:39.385109+08	56753	2026-04-11	CHECKOUT	NORMAL	2026-04-11 20:02:39.385109+08	2026-04-11 23:10:19.784593+08	0	\N	DONE
73	90	2026-04-11 20:02:39.385109+08	16908	2026-04-11	CHECKOUT	ABSENT	2026-04-11 20:02:39.385109+08	2026-04-12 05:03:11.497654+08	0	\N	DONE
71	90	2026-04-11 20:02:39.385109+08	72494	2026-04-11	CHECKOUT	NORMAL	2026-04-11 20:02:39.385109+08	2026-04-11 23:01:37.557548+08	0	\N	DONE
114	121	2026-04-12 20:01:49.863666+08	4257	2026-04-12	CHECKOUT	NORMAL	2026-04-12 20:01:49.863666+08	2026-04-12 23:15:24.163382+08	0	\N	DONE
117	121	2026-04-12 20:01:49.863666+08	29337	2026-04-12	CHECKOUT	NORMAL	2026-04-12 20:01:49.863666+08	2026-04-12 23:15:24.444287+08	0	\N	DONE
120	121	2026-04-12 20:01:49.863666+08	56753	2026-04-12	CHECKOUT	NORMAL	2026-04-12 20:01:49.863666+08	2026-04-12 23:15:24.633959+08	0	\N	DONE
108	111	2026-04-12 11:04:31.884673+08	74114	2026-04-12	CHECKIN	NORMAL	2026-04-12 11:04:31.884673+08	2026-04-12 13:39:12.054733+08	0	\N	DONE
72	90	2026-04-11 20:02:39.385109+08	4257	2026-04-11	CHECKOUT	NORMAL	2026-04-11 20:02:39.385109+08	2026-04-11 23:10:20.73016+08	0	\N	DONE
56	60	2026-04-11 11:01:59.799246+08	56759	2026-04-11	CHECKIN	ABSENT	2026-04-11 11:01:59.799246+08	2026-04-11 20:02:46.078594+08	0	\N	DONE
52	60	2026-04-11 11:01:59.799246+08	31088	2026-04-11	CHECKIN	ABSENT	2026-04-11 11:01:59.799246+08	2026-04-11 20:02:46.276031+08	0	\N	DONE
49	60	2026-04-11 11:01:59.799246+08	16908	2026-04-11	CHECKIN	ABSENT	2026-04-11 11:01:59.799246+08	2026-04-11 20:02:46.564729+08	0	\N	DONE
113	121	2026-04-12 20:01:49.863666+08	72494	2026-04-12	CHECKOUT	NORMAL	2026-04-12 20:01:49.863666+08	2026-04-12 23:35:33.869374+08	0	\N	DONE
90	99	2026-04-12 01:58:39.747764+08	51761	2026-04-12	CHECKIN	ABSENT	2026-04-12 01:58:39.747764+08	2026-04-12 08:13:57.425554+08	0	\N	DONE
77	90	2026-04-11 20:02:39.385109+08	55516	2026-04-11	CHECKOUT	NORMAL	2026-04-11 20:02:39.385109+08	2026-04-11 23:05:13.25817+08	0	\N	DONE
91	99	2026-04-12 01:58:39.747764+08	51964	2026-04-12	CHECKIN	ABSENT	2026-04-12 01:58:39.747764+08	2026-04-12 08:13:57.712844+08	0	\N	DONE
80	90	2026-04-11 20:02:39.385109+08	56773	2026-04-11	CHECKOUT	NORMAL	2026-04-11 20:02:39.385109+08	2026-04-11 23:05:14.059611+08	0	\N	DONE
81	90	2026-04-11 20:02:39.385109+08	58073	2026-04-11	CHECKOUT	NORMAL	2026-04-11 20:02:39.385109+08	2026-04-11 23:05:14.260419+08	0	\N	DONE
99	111	2026-04-12 11:04:31.884673+08	29337	2026-04-12	CHECKIN	NORMAL	2026-04-12 11:04:31.884673+08	2026-04-12 13:44:14.802388+08	0	\N	DONE
83	90	2026-04-11 20:02:39.385109+08	72357	2026-04-11	CHECKOUT	NORMAL	2026-04-11 20:02:39.385109+08	2026-04-11 23:05:14.863474+08	0	\N	DONE
85	90	2026-04-11 20:02:39.385109+08	74168	2026-04-11	CHECKOUT	NORMAL	2026-04-11 20:02:39.385109+08	2026-04-11 23:05:15.577293+08	0	\N	DONE
96	111	2026-04-12 11:04:31.884673+08	4257	2026-04-12	CHECKIN	NORMAL	2026-04-12 11:04:31.884673+08	2026-04-12 13:34:03.508064+08	0	\N	DONE
95	111	2026-04-12 11:04:31.884673+08	72494	2026-04-12	CHECKIN	NORMAL	2026-04-12 11:04:31.884673+08	2026-04-12 12:53:14.062826+08	0	\N	DONE
70	86	2026-04-11 20:02:37.525381+08	51964	2026-04-11	CHECKOUT	ABSENT	2026-04-11 20:02:37.525381+08	2026-04-12 02:14:51.944375+08	0	\N	DONE
87	90	2026-04-11 20:02:39.385109+08	74314	2026-04-11	CHECKOUT	NORMAL	2026-04-11 20:02:39.385109+08	2026-04-11 23:05:16.172055+08	0	\N	DONE
116	121	2026-04-12 20:01:49.863666+08	17025	2026-04-12	CHECKOUT	NORMAL	2026-04-12 20:01:49.863666+08	2026-04-12 23:05:14.912315+08	0	\N	DONE
132	131	2026-04-13 11:04:03.526078+08	51761	2026-04-13	CHECKIN	ABSENT	2026-04-13 11:04:03.526078+08	2026-04-13 20:02:49.303727+08	0	\N	DONE
107	111	2026-04-12 11:04:31.884673+08	72357	2026-04-12	CHECKIN	NORMAL	2026-04-12 11:04:31.884673+08	2026-04-12 13:44:16.482469+08	0	\N	DONE
133	131	2026-04-13 11:04:03.526078+08	51964	2026-04-13	CHECKIN	ABSENT	2026-04-13 11:04:03.526078+08	2026-04-13 20:02:49.60479+08	0	\N	DONE
119	121	2026-04-12 20:01:49.863666+08	55516	2026-04-12	CHECKOUT	NORMAL	2026-04-12 20:01:49.863666+08	2026-04-12 23:05:15.800787+08	0	\N	DONE
102	111	2026-04-12 11:04:31.884673+08	56753	2026-04-12	CHECKIN	NORMAL	2026-04-12 11:04:31.884673+08	2026-04-12 13:34:04.986061+08	0	\N	DONE
110	111	2026-04-12 11:04:31.884673+08	74306	2026-04-12	CHECKIN	NORMAL	2026-04-12 11:04:31.884673+08	2026-04-12 13:44:16.958861+08	0	\N	DONE
75	90	2026-04-11 20:02:39.385109+08	29337	2026-04-11	CHECKOUT	NORMAL	2026-04-11 20:02:39.385109+08	2026-04-11 23:05:17.191969+08	0	\N	DONE
104	111	2026-04-12 11:04:31.884673+08	56773	2026-04-12	CHECKIN	NORMAL	2026-04-12 11:04:31.884673+08	2026-04-12 13:34:05.730689+08	0	\N	DONE
121	121	2026-04-12 20:01:49.863666+08	56759	2026-04-12	CHECKOUT	NORMAL	2026-04-12 20:01:49.863666+08	2026-04-12 23:05:16.274957+08	0	\N	DONE
92	109	2026-04-12 10:04:13.297655+08	7122	2026-04-12	CHECKOUT	ABSENT	2026-04-12 10:04:13.297655+08	2026-04-12 19:01:33.947976+08	0	\N	DONE
93	109	2026-04-12 10:04:13.297655+08	51761	2026-04-12	CHECKOUT	ABSENT	2026-04-12 10:04:13.297655+08	2026-04-12 19:01:34.274413+08	0	\N	DONE
101	111	2026-04-12 11:04:31.884673+08	55516	2026-04-12	CHECKIN	NORMAL	2026-04-12 11:04:31.884673+08	2026-04-12 13:49:19.954865+08	0	\N	DONE
94	109	2026-04-12 10:04:13.297655+08	51964	2026-04-12	CHECKOUT	ABSENT	2026-04-12 10:04:13.297655+08	2026-04-12 19:01:34.474787+08	0	\N	DONE
103	111	2026-04-12 11:04:31.884673+08	56759	2026-04-12	CHECKIN	NORMAL	2026-04-12 11:04:31.884673+08	2026-04-12 13:49:20.254107+08	0	\N	DONE
105	111	2026-04-12 11:04:31.884673+08	58073	2026-04-12	CHECKIN	NORMAL	2026-04-12 11:04:31.884673+08	2026-04-12 13:49:20.57828+08	0	\N	DONE
106	111	2026-04-12 11:04:31.884673+08	59242	2026-04-12	CHECKIN	NORMAL	2026-04-12 11:04:31.884673+08	2026-04-12 13:49:20.890318+08	0	\N	DONE
109	111	2026-04-12 11:04:31.884673+08	74168	2026-04-12	CHECKIN	NORMAL	2026-04-12 11:04:31.884673+08	2026-04-12 13:49:21.202797+08	0	\N	DONE
111	111	2026-04-12 11:04:31.884673+08	74314	2026-04-12	CHECKIN	NORMAL	2026-04-12 11:04:31.884673+08	2026-04-12 13:49:21.372642+08	0	\N	DONE
124	121	2026-04-12 20:01:49.863666+08	59242	2026-04-12	CHECKOUT	NORMAL	2026-04-12 20:01:49.863666+08	2026-04-12 23:05:16.938309+08	0	\N	DONE
125	121	2026-04-12 20:01:49.863666+08	72357	2026-04-12	CHECKOUT	NORMAL	2026-04-12 20:01:49.863666+08	2026-04-12 23:05:17.242824+08	0	\N	DONE
130	121	2026-04-12 20:01:49.863666+08	74322	2026-04-12	CHECKOUT	NORMAL	2026-04-12 20:01:49.863666+08	2026-04-12 23:50:39.064017+08	0	\N	DONE
142	132	2026-04-13 11:04:03.661526+08	56759	2026-04-13	CHECKIN	NORMAL	2026-04-13 11:04:03.661526+08	2026-04-13 13:57:01.605171+08	0	\N	DONE
279	181	2026-04-30 20:00:07.293453+08	51761	2026-04-30	CHECKOUT	NONE	2026-04-30 20:00:07.293453+08	2026-04-30 20:46:22.860757+08	0	\N	PENDING
148	132	2026-04-13 11:04:03.661526+08	74168	2026-04-13	CHECKIN	NORMAL	2026-04-13 11:04:03.661526+08	2026-04-13 14:02:11.474453+08	0	\N	DONE
154	142	2026-04-13 20:02:47.309731+08	51964	2026-04-13	CHECKOUT	ABSENT	2026-04-13 20:02:47.309731+08	2026-04-14 05:04:28.362382+08	0	\N	DONE
176	150	2026-04-14 11:04:54.791184+08	72494	2026-04-14	CHECKIN	NORMAL	2026-04-14 11:04:54.791184+08	2026-04-14 13:58:04.544504+08	0	\N	DONE
168	143	2026-04-13 20:02:48.20828+08	74114	2026-04-13	CHECKOUT	NORMAL	2026-04-13 20:02:48.20828+08	2026-04-13 23:13:44.838826+08	0	\N	DONE
126	121	2026-04-12 20:01:49.863666+08	74114	2026-04-12	CHECKOUT	NORMAL	2026-04-12 20:01:49.863666+08	2026-04-12 23:10:21.428119+08	0	\N	DONE
175	149	2026-04-14 11:04:54.656402+08	51964	2026-04-14	CHECKIN	ABSENT	2026-04-14 11:04:54.656402+08	2026-04-14 20:03:32.937615+08	0	\N	DONE
174	149	2026-04-14 11:04:54.656402+08	51761	2026-04-14	CHECKIN	ABSENT	2026-04-14 11:04:54.656402+08	2026-04-14 20:03:33.227982+08	0	\N	DONE
146	132	2026-04-13 11:04:03.661526+08	72357	2026-04-13	CHECKIN	NORMAL	2026-04-13 11:04:03.661526+08	2026-04-13 13:41:52.495803+08	0	\N	DONE
127	121	2026-04-12 20:01:49.863666+08	74168	2026-04-12	CHECKOUT	NORMAL	2026-04-12 20:01:49.863666+08	2026-04-12 23:15:24.930264+08	0	\N	DONE
164	143	2026-04-13 20:02:48.20828+08	56773	2026-04-13	CHECKOUT	NORMAL	2026-04-13 20:02:48.20828+08	2026-04-13 23:18:48.73536+08	0	\N	DONE
128	121	2026-04-12 20:01:49.863666+08	74306	2026-04-12	CHECKOUT	NORMAL	2026-04-12 20:01:49.863666+08	2026-04-12 23:15:25.105941+08	0	\N	DONE
131	131	2026-04-13 11:04:03.526078+08	7122	2026-04-13	CHECKIN	ABSENT	2026-04-13 11:04:03.526078+08	2026-04-13 20:02:49.022912+08	0	\N	DONE
169	143	2026-04-13 20:02:48.20828+08	74168	2026-04-13	CHECKOUT	NORMAL	2026-04-13 20:02:48.20828+08	2026-04-13 23:18:49.037721+08	0	\N	DONE
138	132	2026-04-13 11:04:03.661526+08	29337	2026-04-13	CHECKIN	NORMAL	2026-04-13 11:04:03.661526+08	2026-04-13 13:46:54.696019+08	0	\N	DONE
122	121	2026-04-12 20:01:49.863666+08	56773	2026-04-12	CHECKOUT	NORMAL	2026-04-12 20:01:49.863666+08	2026-04-12 23:05:16.569762+08	0	\N	DONE
149	132	2026-04-13 11:04:03.661526+08	74306	2026-04-13	CHECKIN	NORMAL	2026-04-13 11:04:03.661526+08	2026-04-13 13:26:37.793546+08	0	\N	DONE
123	121	2026-04-12 20:01:49.863666+08	58073	2026-04-12	CHECKOUT	NORMAL	2026-04-12 20:01:49.863666+08	2026-04-12 23:05:16.753695+08	0	\N	DONE
144	132	2026-04-13 11:04:03.661526+08	58073	2026-04-13	CHECKIN	NORMAL	2026-04-13 11:04:03.661526+08	2026-04-13 13:46:55.751254+08	0	\N	DONE
180	150	2026-04-14 11:04:54.791184+08	29337	2026-04-14	CHECKIN	NORMAL	2026-04-14 11:04:54.791184+08	2026-04-14 13:32:38.611017+08	0	\N	DONE
129	121	2026-04-12 20:01:49.863666+08	74314	2026-04-12	CHECKOUT	NORMAL	2026-04-12 20:01:49.863666+08	2026-04-12 23:30:31.860557+08	0	\N	DONE
196	157	2026-04-14 20:03:31.52835+08	51964	2026-04-14	CHECKOUT	ABSENT	2026-04-14 20:03:31.52835+08	2026-04-19 14:32:36.65081+08	0	\N	DONE
155	143	2026-04-13 20:02:48.20828+08	72494	2026-04-13	CHECKOUT	NORMAL	2026-04-13 20:02:48.20828+08	2026-04-13 23:28:55.26681+08	0	\N	DONE
195	157	2026-04-14 20:03:31.52835+08	51761	2026-04-14	CHECKOUT	ABSENT	2026-04-14 20:03:31.52835+08	2026-04-19 14:32:36.950183+08	0	\N	DONE
179	150	2026-04-14 11:04:54.791184+08	17025	2026-04-14	CHECKIN	NORMAL	2026-04-14 11:04:54.791184+08	2026-04-14 13:47:53.527216+08	0	\N	DONE
136	132	2026-04-13 11:04:03.661526+08	16908	2026-04-13	CHECKIN	NORMAL	2026-04-13 11:04:03.661526+08	2026-04-13 13:51:58.542594+08	0	\N	DONE
139	132	2026-04-13 11:04:03.661526+08	31088	2026-04-13	CHECKIN	NORMAL	2026-04-13 11:04:03.661526+08	2026-04-13 13:51:58.711456+08	0	\N	DONE
194	157	2026-04-14 20:03:31.52835+08	7122	2026-04-14	CHECKOUT	ABSENT	2026-04-14 20:03:31.52835+08	2026-04-19 14:32:37.241706+08	0	\N	DONE
140	132	2026-04-13 11:04:03.661526+08	55516	2026-04-13	CHECKIN	NORMAL	2026-04-13 11:04:03.661526+08	2026-04-13 13:51:58.997462+08	0	\N	DONE
156	143	2026-04-13 20:02:48.20828+08	4257	2026-04-13	CHECKOUT	NORMAL	2026-04-13 20:02:48.20828+08	2026-04-13 23:03:33.24666+08	0	\N	DONE
141	132	2026-04-13 11:04:03.661526+08	56753	2026-04-13	CHECKIN	NORMAL	2026-04-13 11:04:03.661526+08	2026-04-13 13:51:59.1768+08	0	\N	DONE
157	143	2026-04-13 20:02:48.20828+08	16908	2026-04-13	CHECKOUT	NORMAL	2026-04-13 20:02:48.20828+08	2026-04-13 23:03:33.543014+08	0	\N	DONE
145	132	2026-04-13 11:04:03.661526+08	59242	2026-04-13	CHECKIN	NORMAL	2026-04-13 11:04:03.661526+08	2026-04-13 13:51:59.564457+08	0	\N	DONE
158	143	2026-04-13 20:02:48.20828+08	17025	2026-04-13	CHECKOUT	NORMAL	2026-04-13 20:02:48.20828+08	2026-04-13 23:03:33.721578+08	0	\N	DONE
147	132	2026-04-13 11:04:03.661526+08	74114	2026-04-13	CHECKIN	NORMAL	2026-04-13 11:04:03.661526+08	2026-04-13 13:51:59.740271+08	0	\N	DONE
170	143	2026-04-13 20:02:48.20828+08	74306	2026-04-13	CHECKOUT	NORMAL	2026-04-13 20:02:48.20828+08	2026-04-13 23:33:58.484589+08	0	\N	DONE
159	143	2026-04-13 20:02:48.20828+08	29337	2026-04-13	CHECKOUT	NORMAL	2026-04-13 20:02:48.20828+08	2026-04-13 23:03:33.907434+08	0	\N	DONE
151	132	2026-04-13 11:04:03.661526+08	74322	2026-04-13	CHECKIN	NORMAL	2026-04-13 11:04:03.661526+08	2026-04-13 13:52:00.093713+08	0	\N	DONE
184	150	2026-04-14 11:04:54.791184+08	56759	2026-04-14	CHECKIN	NORMAL	2026-04-14 11:04:54.791184+08	2026-04-14 13:47:56.197453+08	0	\N	DONE
161	143	2026-04-13 20:02:48.20828+08	55516	2026-04-13	CHECKOUT	NORMAL	2026-04-13 20:02:48.20828+08	2026-04-13 23:03:34.29517+08	0	\N	DONE
178	150	2026-04-14 11:04:54.791184+08	16908	2026-04-14	CHECKIN	NORMAL	2026-04-14 11:04:54.791184+08	2026-04-14 13:52:59.381791+08	0	\N	DONE
165	143	2026-04-13 20:02:48.20828+08	58073	2026-04-13	CHECKOUT	NORMAL	2026-04-13 20:02:48.20828+08	2026-04-13 23:03:35.071979+08	0	\N	DONE
166	143	2026-04-13 20:02:48.20828+08	59242	2026-04-13	CHECKOUT	NORMAL	2026-04-13 20:02:48.20828+08	2026-04-13 23:03:35.354895+08	0	\N	DONE
181	150	2026-04-14 11:04:54.791184+08	31088	2026-04-14	CHECKIN	NORMAL	2026-04-14 11:04:54.791184+08	2026-04-14 13:52:59.779974+08	0	\N	DONE
172	143	2026-04-13 20:02:48.20828+08	74322	2026-04-13	CHECKOUT	NORMAL	2026-04-13 20:02:48.20828+08	2026-04-13 23:49:07.442212+08	0	\N	DONE
134	132	2026-04-13 11:04:03.661526+08	72494	2026-04-13	CHECKIN	NORMAL	2026-04-13 11:04:03.661526+08	2026-04-13 13:36:45.29944+08	0	\N	DONE
182	150	2026-04-14 11:04:54.791184+08	55516	2026-04-14	CHECKIN	NORMAL	2026-04-14 11:04:54.791184+08	2026-04-14 13:52:59.974251+08	0	\N	DONE
150	132	2026-04-13 11:04:03.661526+08	74314	2026-04-13	CHECKIN	NORMAL	2026-04-13 11:04:03.661526+08	2026-04-13 13:21:32.491375+08	0	\N	DONE
135	132	2026-04-13 11:04:03.661526+08	4257	2026-04-13	CHECKIN	NORMAL	2026-04-13 11:04:03.661526+08	2026-04-13 13:36:45.472513+08	0	\N	DONE
183	150	2026-04-14 11:04:54.791184+08	56753	2026-04-14	CHECKIN	NORMAL	2026-04-14 11:04:54.791184+08	2026-04-14 13:53:00.168977+08	0	\N	DONE
171	143	2026-04-13 20:02:48.20828+08	74314	2026-04-13	CHECKOUT	NORMAL	2026-04-13 20:02:48.20828+08	2026-04-13 23:03:37.173142+08	0	\N	DONE
137	132	2026-04-13 11:04:03.661526+08	17025	2026-04-13	CHECKIN	NORMAL	2026-04-13 11:04:03.661526+08	2026-04-13 13:36:46.071305+08	0	\N	DONE
177	150	2026-04-14 11:04:54.791184+08	4257	2026-04-14	CHECKIN	NORMAL	2026-04-14 11:04:54.791184+08	2026-04-14 13:37:45.365251+08	0	\N	DONE
160	143	2026-04-13 20:02:48.20828+08	31088	2026-04-13	CHECKOUT	NORMAL	2026-04-13 20:02:48.20828+08	2026-04-13 23:08:40.103152+08	0	\N	DONE
143	132	2026-04-13 11:04:03.661526+08	56773	2026-04-13	CHECKIN	NORMAL	2026-04-13 11:04:03.661526+08	2026-04-13 13:36:47.552661+08	0	\N	DONE
162	143	2026-04-13 20:02:48.20828+08	56753	2026-04-13	CHECKOUT	NORMAL	2026-04-13 20:02:48.20828+08	2026-04-13 23:08:40.389846+08	0	\N	DONE
163	143	2026-04-13 20:02:48.20828+08	56759	2026-04-13	CHECKOUT	NORMAL	2026-04-13 20:02:48.20828+08	2026-04-13 23:08:40.699502+08	0	\N	DONE
167	143	2026-04-13 20:02:48.20828+08	72357	2026-04-13	CHECKOUT	NORMAL	2026-04-13 20:02:48.20828+08	2026-04-13 23:08:41.089161+08	0	\N	DONE
263	177	2026-04-30 19:08:48.97153+08	17025	2026-04-30	CHECKIN	ABSENT	2026-04-30 19:08:48.97153+08	2026-04-30 20:00:09.855579+08	0	\N	DONE
228	165	2026-04-19 14:32:29.425785+08	58073	2026-04-19	CHECKIN	NORMAL	2026-04-19 14:32:29.425785+08	2026-04-19 14:37:45.074191+08	0	\N	DONE
190	150	2026-04-14 11:04:54.791184+08	74168	2026-04-14	CHECKIN	NORMAL	2026-04-14 11:04:54.791184+08	2026-04-14 13:37:47.484175+08	0	\N	DONE
242	170	2026-04-19 20:03:06.116069+08	17025	2026-04-19	CHECKOUT	NORMAL	2026-04-19 20:03:06.116069+08	2026-04-19 23:03:19.495631+08	0	\N	DONE
229	165	2026-04-19 14:32:29.425785+08	59242	2026-04-19	CHECKIN	NORMAL	2026-04-19 14:32:29.425785+08	2026-04-19 14:37:45.261921+08	0	\N	DONE
264	177	2026-04-30 19:08:48.97153+08	29337	2026-04-30	CHECKIN	ABSENT	2026-04-30 19:08:48.97153+08	2026-04-30 20:00:10.267479+08	0	\N	DONE
230	165	2026-04-19 14:32:29.425785+08	72357	2026-04-19	CHECKIN	NORMAL	2026-04-19 14:32:29.425785+08	2026-04-19 14:37:45.545918+08	0	\N	DONE
231	165	2026-04-19 14:32:29.425785+08	74114	2026-04-19	CHECKIN	NORMAL	2026-04-19 14:32:29.425785+08	2026-04-19 14:37:45.842873+08	0	\N	DONE
265	177	2026-04-30 19:08:48.97153+08	31088	2026-04-30	CHECKIN	ABSENT	2026-04-30 19:08:48.97153+08	2026-04-30 20:00:10.444859+08	0	\N	DONE
232	165	2026-04-19 14:32:29.425785+08	74168	2026-04-19	CHECKIN	NORMAL	2026-04-19 14:32:29.425785+08	2026-04-19 14:37:46.146952+08	0	\N	DONE
244	170	2026-04-19 20:03:06.116069+08	31088	2026-04-19	CHECKOUT	NORMAL	2026-04-19 20:03:06.116069+08	2026-04-19 23:03:20.28058+08	0	\N	DONE
233	165	2026-04-19 14:32:29.425785+08	74306	2026-04-19	CHECKIN	NORMAL	2026-04-19 14:32:29.425785+08	2026-04-19 14:37:46.426978+08	0	\N	DONE
189	150	2026-04-14 11:04:54.791184+08	74114	2026-04-14	CHECKIN	NORMAL	2026-04-14 11:04:54.791184+08	2026-04-14 14:03:14.776279+08	0	\N	DONE
234	165	2026-04-19 14:32:29.425785+08	74314	2026-04-19	CHECKIN	NORMAL	2026-04-19 14:32:29.425785+08	2026-04-19 14:37:46.724547+08	0	\N	DONE
245	170	2026-04-19 20:03:06.116069+08	55516	2026-04-19	CHECKOUT	NORMAL	2026-04-19 20:03:06.116069+08	2026-04-19 23:03:20.812601+08	0	\N	DONE
235	165	2026-04-19 14:32:29.425785+08	74322	2026-04-19	CHECKIN	NORMAL	2026-04-19 14:32:29.425785+08	2026-04-19 14:37:47.039738+08	0	\N	DONE
261	177	2026-04-30 19:08:48.97153+08	4257	2026-04-30	CHECKIN	ABSENT	2026-04-30 19:08:48.97153+08	2026-04-30 20:00:10.863218+08	0	\N	DONE
191	150	2026-04-14 11:04:54.791184+08	74306	2026-04-14	CHECKIN	NORMAL	2026-04-14 11:04:54.791184+08	2026-04-14 13:32:40.224292+08	0	\N	DONE
218	165	2026-04-19 14:32:29.425785+08	72494	2026-04-19	CHECKIN	NORMAL	2026-04-19 14:32:29.425785+08	2026-04-19 14:37:47.233946+08	0	\N	DONE
281	182	2026-04-30 20:00:07.851541+08	72494	2026-04-30	CHECKOUT	NONE	2026-04-30 20:00:07.851541+08	2026-04-30 20:46:27.663211+08	0	\N	PENDING
204	158	2026-04-14 20:03:32.126795+08	56753	2026-04-14	CHECKOUT	NORMAL	2026-04-14 20:03:32.126795+08	2026-04-14 23:19:17.948211+08	0	\N	DONE
219	165	2026-04-19 14:32:29.425785+08	4257	2026-04-19	CHECKIN	NORMAL	2026-04-19 14:32:29.425785+08	2026-04-19 14:37:47.54367+08	0	\N	DONE
260	177	2026-04-30 19:08:48.97153+08	72494	2026-04-30	CHECKIN	ABSENT	2026-04-30 19:08:48.97153+08	2026-04-30 20:00:11.170901+08	0	\N	DONE
220	165	2026-04-19 14:32:29.425785+08	16908	2026-04-19	CHECKIN	NORMAL	2026-04-19 14:32:29.425785+08	2026-04-19 14:37:47.850535+08	0	\N	DONE
221	165	2026-04-19 14:32:29.425785+08	17025	2026-04-19	CHECKIN	NORMAL	2026-04-19 14:32:29.425785+08	2026-04-19 14:37:48.027352+08	0	\N	DONE
282	182	2026-04-30 20:00:07.851541+08	4257	2026-04-30	CHECKOUT	NONE	2026-04-30 20:00:07.851541+08	2026-04-30 20:46:27.97191+08	0	\N	PENDING
222	165	2026-04-19 14:32:29.425785+08	29337	2026-04-19	CHECKIN	NORMAL	2026-04-19 14:32:29.425785+08	2026-04-19 14:37:48.228602+08	0	\N	DONE
243	170	2026-04-19 20:03:06.116069+08	29337	2026-04-19	CHECKOUT	NORMAL	2026-04-19 20:03:06.116069+08	2026-04-19 23:08:28.319711+08	0	\N	DONE
223	165	2026-04-19 14:32:29.425785+08	31088	2026-04-19	CHECKIN	NORMAL	2026-04-19 14:32:29.425785+08	2026-04-19 14:37:48.435693+08	0	\N	DONE
224	165	2026-04-19 14:32:29.425785+08	55516	2026-04-19	CHECKIN	NORMAL	2026-04-19 14:32:29.425785+08	2026-04-19 14:37:48.723+08	0	\N	DONE
225	165	2026-04-19 14:32:29.425785+08	56753	2026-04-19	CHECKIN	NORMAL	2026-04-19 14:32:29.425785+08	2026-04-19 14:37:48.907155+08	0	\N	DONE
173	149	2026-04-14 11:04:54.656402+08	7122	2026-04-14	CHECKIN	ABSENT	2026-04-14 11:04:54.656402+08	2026-04-14 20:03:32.749918+08	0	\N	DONE
226	165	2026-04-19 14:32:29.425785+08	56759	2026-04-19	CHECKIN	NORMAL	2026-04-19 14:32:29.425785+08	2026-04-19 14:37:49.202807+08	0	\N	DONE
186	150	2026-04-14 11:04:54.791184+08	58073	2026-04-14	CHECKIN	NORMAL	2026-04-14 11:04:54.791184+08	2026-04-14 13:53:00.361779+08	0	\N	DONE
187	150	2026-04-14 11:04:54.791184+08	59242	2026-04-14	CHECKIN	ABSENT	2026-04-14 11:04:54.791184+08	2026-04-14 20:03:33.416976+08	0	\N	DONE
188	150	2026-04-14 11:04:54.791184+08	72357	2026-04-14	CHECKIN	ABSENT	2026-04-14 11:04:54.791184+08	2026-04-14 20:03:33.704417+08	0	\N	DONE
227	165	2026-04-19 14:32:29.425785+08	56773	2026-04-19	CHECKIN	NORMAL	2026-04-19 14:32:29.425785+08	2026-04-19 14:37:49.389848+08	0	\N	DONE
192	150	2026-04-14 11:04:54.791184+08	74314	2026-04-14	CHECKIN	ABSENT	2026-04-14 11:04:54.791184+08	2026-04-14 20:03:33.999467+08	0	\N	DONE
193	150	2026-04-14 11:04:54.791184+08	74322	2026-04-14	CHECKIN	ABSENT	2026-04-14 11:04:54.791184+08	2026-04-14 20:03:34.205032+08	0	\N	DONE
240	170	2026-04-19 20:03:06.116069+08	4257	2026-04-19	CHECKOUT	NORMAL	2026-04-19 20:03:06.116069+08	2026-04-19 23:08:32.037331+08	0	\N	DONE
185	150	2026-04-14 11:04:54.791184+08	56773	2026-04-14	CHECKIN	NORMAL	2026-04-14 11:04:54.791184+08	2026-04-14 13:37:46.360625+08	0	\N	DONE
199	158	2026-04-14 20:03:32.126795+08	16908	2026-04-14	CHECKOUT	NORMAL	2026-04-14 20:03:32.126795+08	2026-04-14 23:03:56.400678+08	0	\N	DONE
200	158	2026-04-14 20:03:32.126795+08	17025	2026-04-14	CHECKOUT	NORMAL	2026-04-14 20:03:32.126795+08	2026-04-14 23:03:56.646735+08	0	\N	DONE
203	158	2026-04-14 20:03:32.126795+08	55516	2026-04-14	CHECKOUT	NORMAL	2026-04-14 20:03:32.126795+08	2026-04-14 23:03:57.700561+08	0	\N	DONE
241	170	2026-04-19 20:03:06.116069+08	16908	2026-04-19	CHECKOUT	NORMAL	2026-04-19 20:03:06.116069+08	2026-04-19 23:18:41.948243+08	0	\N	DONE
215	161	2026-04-19 14:32:27.205164+08	7122	2026-04-19	CHECKIN	ABSENT	2026-04-19 14:32:27.205164+08	2026-04-19 20:03:06.640191+08	0	\N	DONE
206	158	2026-04-14 20:03:32.126795+08	56773	2026-04-14	CHECKOUT	NORMAL	2026-04-14 20:03:32.126795+08	2026-04-14 23:03:58.867789+08	0	\N	DONE
217	161	2026-04-19 14:32:27.205164+08	51964	2026-04-19	CHECKIN	ABSENT	2026-04-19 14:32:27.205164+08	2026-04-19 20:03:06.835487+08	0	\N	DONE
246	170	2026-04-19 20:03:06.116069+08	56753	2026-04-19	CHECKOUT	ABSENT	2026-04-19 20:03:06.116069+08	2026-04-30 19:08:56.559188+08	0	\N	DONE
239	170	2026-04-19 20:03:06.116069+08	72494	2026-04-19	CHECKOUT	NORMAL	2026-04-19 20:03:06.116069+08	2026-04-30 19:08:56.873899+08	0	\N	DONE
214	158	2026-04-14 20:03:32.126795+08	74322	2026-04-14	CHECKOUT	ABSENT	2026-04-14 20:03:32.126795+08	2026-04-19 14:32:37.442497+08	0	\N	DONE
211	158	2026-04-14 20:03:32.126795+08	74168	2026-04-14	CHECKOUT	NORMAL	2026-04-14 20:03:32.126795+08	2026-04-14 23:04:00.529325+08	0	\N	DONE
208	158	2026-04-14 20:03:32.126795+08	59242	2026-04-14	CHECKOUT	ABSENT	2026-04-14 20:03:32.126795+08	2026-04-19 14:32:37.641833+08	0	\N	DONE
209	158	2026-04-14 20:03:32.126795+08	72357	2026-04-14	CHECKOUT	ABSENT	2026-04-14 20:03:32.126795+08	2026-04-19 14:32:37.95369+08	0	\N	DONE
212	158	2026-04-14 20:03:32.126795+08	74306	2026-04-14	CHECKOUT	ABSENT	2026-04-14 20:03:32.126795+08	2026-04-19 14:32:38.147597+08	0	\N	DONE
213	158	2026-04-14 20:03:32.126795+08	74314	2026-04-14	CHECKOUT	ABSENT	2026-04-14 20:03:32.126795+08	2026-04-19 14:32:38.325728+08	0	\N	DONE
197	158	2026-04-14 20:03:32.126795+08	72494	2026-04-14	CHECKOUT	NORMAL	2026-04-14 20:03:32.126795+08	2026-04-15 00:05:07.871651+08	0	\N	DONE
198	158	2026-04-14 20:03:32.126795+08	4257	2026-04-14	CHECKOUT	NORMAL	2026-04-14 20:03:32.126795+08	2026-04-14 23:09:04.960931+08	0	\N	DONE
201	158	2026-04-14 20:03:32.126795+08	29337	2026-04-14	CHECKOUT	NORMAL	2026-04-14 20:03:32.126795+08	2026-04-14 23:09:05.199209+08	0	\N	DONE
202	158	2026-04-14 20:03:32.126795+08	31088	2026-04-14	CHECKOUT	NORMAL	2026-04-14 20:03:32.126795+08	2026-04-14 23:09:05.440239+08	0	\N	DONE
205	158	2026-04-14 20:03:32.126795+08	56759	2026-04-14	CHECKOUT	NORMAL	2026-04-14 20:03:32.126795+08	2026-04-14 23:09:06.119198+08	0	\N	DONE
207	158	2026-04-14 20:03:32.126795+08	58073	2026-04-14	CHECKOUT	NORMAL	2026-04-14 20:03:32.126795+08	2026-04-14 23:09:06.360669+08	0	\N	DONE
210	158	2026-04-14 20:03:32.126795+08	74114	2026-04-14	CHECKOUT	NORMAL	2026-04-14 20:03:32.126795+08	2026-04-14 23:09:07.272482+08	0	\N	DONE
248	170	2026-04-19 20:03:06.116069+08	56773	2026-04-19	CHECKOUT	NORMAL	2026-04-19 20:03:06.116069+08	2026-04-19 23:03:21.374437+08	0	\N	DONE
216	161	2026-04-19 14:32:27.205164+08	51761	2026-04-19	CHECKIN	ABSENT	2026-04-19 14:32:27.205164+08	2026-04-19 20:03:07.035671+08	0	\N	DONE
256	170	2026-04-19 20:03:06.116069+08	74322	2026-04-19	CHECKOUT	NORMAL	2026-04-19 20:03:06.116069+08	2026-04-19 23:28:49.124215+08	0	\N	DONE
251	170	2026-04-19 20:03:06.116069+08	72357	2026-04-19	CHECKOUT	NORMAL	2026-04-19 20:03:06.116069+08	2026-04-19 23:03:22.44063+08	0	\N	DONE
258	173	2026-04-30 19:08:47.282972+08	51761	2026-04-30	CHECKIN	ABSENT	2026-04-30 19:08:47.282972+08	2026-04-30 20:00:08.640212+08	0	\N	DONE
255	170	2026-04-19 20:03:06.116069+08	74314	2026-04-19	CHECKOUT	NORMAL	2026-04-19 20:03:06.116069+08	2026-04-19 23:03:23.825654+08	0	\N	DONE
257	173	2026-04-30 19:08:47.282972+08	7122	2026-04-30	CHECKIN	ABSENT	2026-04-30 19:08:47.282972+08	2026-04-30 20:00:08.845472+08	0	\N	DONE
259	173	2026-04-30 19:08:47.282972+08	51964	2026-04-30	CHECKIN	ABSENT	2026-04-30 19:08:47.282972+08	2026-04-30 20:00:09.045129+08	0	\N	DONE
262	177	2026-04-30 19:08:48.97153+08	16908	2026-04-30	CHECKIN	ABSENT	2026-04-30 19:08:48.97153+08	2026-04-30 20:00:09.550317+08	0	\N	DONE
254	170	2026-04-19 20:03:06.116069+08	74306	2026-04-19	CHECKOUT	NORMAL	2026-04-19 20:03:06.116069+08	2026-04-19 23:08:29.264205+08	0	\N	DONE
275	177	2026-04-30 19:08:48.97153+08	74306	2026-04-30	CHECKIN	ABSENT	2026-04-30 19:08:48.97153+08	2026-04-30 20:00:11.452608+08	0	\N	DONE
274	177	2026-04-30 19:08:48.97153+08	74168	2026-04-30	CHECKIN	ABSENT	2026-04-30 19:08:48.97153+08	2026-04-30 20:00:11.641548+08	0	\N	DONE
247	170	2026-04-19 20:03:06.116069+08	56759	2026-04-19	CHECKOUT	NORMAL	2026-04-19 20:03:06.116069+08	2026-04-19 23:08:30.158828+08	0	\N	DONE
249	170	2026-04-19 20:03:06.116069+08	58073	2026-04-19	CHECKOUT	NORMAL	2026-04-19 20:03:06.116069+08	2026-04-19 23:08:30.489627+08	0	\N	DONE
273	177	2026-04-30 19:08:48.97153+08	74114	2026-04-30	CHECKIN	ABSENT	2026-04-30 19:08:48.97153+08	2026-04-30 20:00:12.040317+08	0	\N	DONE
250	170	2026-04-19 20:03:06.116069+08	59242	2026-04-19	CHECKOUT	NORMAL	2026-04-19 20:03:06.116069+08	2026-04-19 23:08:31.030298+08	0	\N	DONE
252	170	2026-04-19 20:03:06.116069+08	74114	2026-04-19	CHECKOUT	NORMAL	2026-04-19 20:03:06.116069+08	2026-04-19 23:08:31.447708+08	0	\N	DONE
272	177	2026-04-30 19:08:48.97153+08	72357	2026-04-30	CHECKIN	ABSENT	2026-04-30 19:08:48.97153+08	2026-04-30 20:00:12.341905+08	0	\N	DONE
271	177	2026-04-30 19:08:48.97153+08	59242	2026-04-30	CHECKIN	ABSENT	2026-04-30 19:08:48.97153+08	2026-04-30 20:00:12.73302+08	0	\N	DONE
270	177	2026-04-30 19:08:48.97153+08	58073	2026-04-30	CHECKIN	ABSENT	2026-04-30 19:08:48.97153+08	2026-04-30 20:00:13.014122+08	0	\N	DONE
269	177	2026-04-30 19:08:48.97153+08	56773	2026-04-30	CHECKIN	ABSENT	2026-04-30 19:08:48.97153+08	2026-04-30 20:00:13.4116+08	0	\N	DONE
268	177	2026-04-30 19:08:48.97153+08	56759	2026-04-30	CHECKIN	ABSENT	2026-04-30 19:08:48.97153+08	2026-04-30 20:00:13.721719+08	0	\N	DONE
266	177	2026-04-30 19:08:48.97153+08	55516	2026-04-30	CHECKIN	ABSENT	2026-04-30 19:08:48.97153+08	2026-04-30 20:00:14.013264+08	0	\N	DONE
236	169	2026-04-19 20:03:05.610862+08	7122	2026-04-19	CHECKOUT	ABSENT	2026-04-19 20:03:05.610862+08	2026-04-30 19:08:55.657862+08	0	\N	DONE
267	177	2026-04-30 19:08:48.97153+08	56753	2026-04-30	CHECKIN	ABSENT	2026-04-30 19:08:48.97153+08	2026-04-30 20:00:14.439559+08	0	\N	DONE
237	169	2026-04-19 20:03:05.610862+08	51761	2026-04-19	CHECKOUT	ABSENT	2026-04-19 20:03:05.610862+08	2026-04-30 19:08:55.970296+08	0	\N	DONE
238	169	2026-04-19 20:03:05.610862+08	51964	2026-04-19	CHECKOUT	ABSENT	2026-04-19 20:03:05.610862+08	2026-04-30 19:08:56.265021+08	0	\N	DONE
277	177	2026-04-30 19:08:48.97153+08	74322	2026-04-30	CHECKIN	ABSENT	2026-04-30 19:08:48.97153+08	2026-04-30 20:00:14.648634+08	0	\N	DONE
276	177	2026-04-30 19:08:48.97153+08	74314	2026-04-30	CHECKIN	ABSENT	2026-04-30 19:08:48.97153+08	2026-04-30 20:00:15.086021+08	0	\N	DONE
253	170	2026-04-19 20:03:06.116069+08	74168	2026-04-19	CHECKOUT	NORMAL	2026-04-19 20:03:06.116069+08	2026-04-19 23:18:41.711149+08	0	\N	DONE
280	181	2026-04-30 20:00:07.293453+08	51964	2026-04-30	CHECKOUT	NONE	2026-04-30 20:00:07.293453+08	2026-04-30 20:46:22.355196+08	0	\N	PENDING
278	181	2026-04-30 20:00:07.293453+08	7122	2026-04-30	CHECKOUT	NONE	2026-04-30 20:00:07.293453+08	2026-04-30 20:46:22.550627+08	0	\N	PENDING
295	182	2026-04-30 20:00:07.851541+08	74168	2026-04-30	CHECKOUT	NONE	2026-04-30 20:00:07.851541+08	2026-04-30 20:46:23.055143+08	0	\N	PENDING
296	182	2026-04-30 20:00:07.851541+08	74306	2026-04-30	CHECKOUT	NONE	2026-04-30 20:00:07.851541+08	2026-04-30 20:46:23.46463+08	0	\N	PENDING
297	182	2026-04-30 20:00:07.851541+08	74314	2026-04-30	CHECKOUT	NONE	2026-04-30 20:00:07.851541+08	2026-04-30 20:46:23.65996+08	0	\N	PENDING
298	182	2026-04-30 20:00:07.851541+08	74322	2026-04-30	CHECKOUT	NONE	2026-04-30 20:00:07.851541+08	2026-04-30 20:46:24.074616+08	0	\N	PENDING
294	182	2026-04-30 20:00:07.851541+08	74114	2026-04-30	CHECKOUT	NONE	2026-04-30 20:00:07.851541+08	2026-04-30 20:46:24.488282+08	0	\N	PENDING
293	182	2026-04-30 20:00:07.851541+08	72357	2026-04-30	CHECKOUT	NONE	2026-04-30 20:00:07.851541+08	2026-04-30 20:46:24.68956+08	0	\N	PENDING
292	182	2026-04-30 20:00:07.851541+08	59242	2026-04-30	CHECKOUT	NONE	2026-04-30 20:00:07.851541+08	2026-04-30 20:46:24.876687+08	0	\N	PENDING
291	182	2026-04-30 20:00:07.851541+08	58073	2026-04-30	CHECKOUT	NONE	2026-04-30 20:00:07.851541+08	2026-04-30 20:46:25.096194+08	0	\N	PENDING
290	182	2026-04-30 20:00:07.851541+08	56773	2026-04-30	CHECKOUT	NONE	2026-04-30 20:00:07.851541+08	2026-04-30 20:46:25.410615+08	0	\N	PENDING
289	182	2026-04-30 20:00:07.851541+08	56759	2026-04-30	CHECKOUT	NONE	2026-04-30 20:00:07.851541+08	2026-04-30 20:46:25.72433+08	0	\N	PENDING
288	182	2026-04-30 20:00:07.851541+08	56753	2026-04-30	CHECKOUT	NONE	2026-04-30 20:00:07.851541+08	2026-04-30 20:46:25.926485+08	0	\N	PENDING
287	182	2026-04-30 20:00:07.851541+08	55516	2026-04-30	CHECKOUT	NONE	2026-04-30 20:00:07.851541+08	2026-04-30 20:46:26.250324+08	0	\N	PENDING
286	182	2026-04-30 20:00:07.851541+08	31088	2026-04-30	CHECKOUT	NONE	2026-04-30 20:00:07.851541+08	2026-04-30 20:46:26.551404+08	0	\N	PENDING
285	182	2026-04-30 20:00:07.851541+08	29337	2026-04-30	CHECKOUT	NONE	2026-04-30 20:00:07.851541+08	2026-04-30 20:46:26.852925+08	0	\N	PENDING
284	182	2026-04-30 20:00:07.851541+08	17025	2026-04-30	CHECKOUT	NONE	2026-04-30 20:00:07.851541+08	2026-04-30 20:46:27.272881+08	0	\N	PENDING
283	182	2026-04-30 20:00:07.851541+08	16908	2026-04-30	CHECKOUT	NONE	2026-04-30 20:00:07.851541+08	2026-04-30 20:46:27.466378+08	0	\N	PENDING
\.


--
-- TOC entry 5292 (class 0 OID 17875)
-- Dependencies: 232
-- Data for Name: clock_records; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.clock_records (id, chat_id, file_id, tg_id, employee_id, shift_id, clock_time) FROM stdin;
11	-1003767543777	AgACAgUAAyEFAATgkCfhAAIC2GnZFKrSDLy8ysHPB0MM9K4Fme-TAAKVDGsbv_HJVkuo4TPiu646AQADAgADeQADOwQ	6332760420	7122	0	2026-04-10 23:18:01.945564+08
12	-1003883297177	AgACAgUAAyEFAATndmmZAAICFmnZFEQZsGO-kEDLLQhdc3xlRnr2AAJiDGsbLFjIVpnQzYJYg5BCAQADAgADeQADOwQ	8352461288	72494	1	2026-04-10 23:34:36.597175+08
13	-1003883297177	AgACAgUAAyEFAATndmmZAAICI2nZxFXVEun_lc8FxTPzvVGltRAZAAJ5D2sbzDvRVlJ9b5_1mDcoAQADAgADeQADOwQ	7020886046	51761	1	2026-04-11 11:47:33.051847+08
14	-1003883297177	AgACAgUAAyEFAATndmmZAAICJWnZ129kEiK8g0yh2wqYMgxmac-0AAKnD2sbzDvRVpJEJH4qWpk8AQADAgADeQADOwQ	8352461288	72494	1	2026-04-11 13:09:42.815619+08
15	-1003883297177	AgACAgUAAyEFAATndmmZAAICJWnZ129kEiK8g0yh2wqYMgxmac-0AAKnD2sbzDvRVpJEJH4qWpk8AQADAgADeQADOwQ	8352461288	72494	1	2026-04-11 13:09:47.789922+08
16	-1003883297177	BQACAgUAAyEFAATndmmZAAICKGnZ2n83w1qnuqLICKIrXfnnWhjVAALDHQACzDvRVokIftSKYTH7OwQ	6562376911	17025	1	2026-04-11 13:22:07.894417+08
17	-1003883297177	AgACAgUAAyEFAATndmmZAAICKmnZ2viIrUV4Pt225XZWiojm5XVhAAKvD2sbzDvRVghATuKnZsq5AQADAgADeQADOwQ	8532682955	74306	1	2026-04-11 13:24:08.747855+08
18	-1003883297177	BQACAgUAAyEFAATndmmZAAICLGnZ23wtj8DnYAeg67e78l1K_XE2AALLHQACzDvRVsVz73SWvBw1OwQ	8233548675	72357	1	2026-04-11 13:26:20.812231+08
19	-1003883297177	AgACAgUAAyEFAATndmmZAAICLmnZ3J4pkqcsfYDf-nwWEQABnTbX6wACsg9rG8w70Va96e-orbWMPQEAAwIAA3kAAzsE	7625966687	56753	1	2026-04-11 13:31:10.329218+08
20	-1003883297177	BQACAgUAAyEFAATndmmZAAICMGnZ3TiD1cBbgDLGKfJhSGFnuCjQAALQHQACzDvRViAhqejfdjVzOwQ	7056750099	4257	1	2026-04-11 13:33:44.882989+08
21	-1003883297177	BQACAgUAAyEFAATndmmZAAICMGnZ3TiD1cBbgDLGKfJhSGFnuCjQAALQHQACzDvRViAhqejfdjVzOwQ	7056750099	4257	1	2026-04-11 13:33:44.951015+08
22	-1003883297177	BQACAgUAAyEFAATndmmZAAICM2nZ3naZ-bQRRFb2zCxwRzRzCwHtAALVHQACzDvRVj-Z4gZKz-JtOwQ	7625201169	56773	1	2026-04-11 13:39:03.318455+08
23	-1003883297177	AgACAgUAAyEFAATndmmZAAICNWnZ3ujW7ryAGspEw-n0JcyjRNQTAAK0D2sbzDvRVu5GBaLy0s36AQADAgADeQADOwQ	7736673658	29337	1	2026-04-11 13:40:58.109409+08
24	-1003883297177	AgACAgUAAyEFAATndmmZAAICN2nZ3zuJcoDU-QNdTbiTRXiycQAB2wACtQ9rG8w70Vaa49NvL2Qc5gEAAwIAA3kAAzsE	7074207060	58073	1	2026-04-11 13:42:19.244462+08
25	-1003883297177	AgACAgUAAyEFAATndmmZAAICOWnZ34ChoJl5HDSOZ8vK5QAB5ZceRAACtw9rG8w70VY5QWFFd8P4awEAAwIAA3kAAzsE	8590155218	74168	1	2026-04-11 13:43:28.288054+08
26	-1003883297177	AgACAgUAAyEFAATndmmZAAICO2nZ34zjljsBooqw6WypyEUarh4cAAK4D2sbzDvRVm6TcYthVsGwAQADAgADeQADOwQ	8763615403	74314	1	2026-04-11 13:43:55.201618+08
27	-1003883297177	BQACAgUAAyEFAATndmmZAAICPWnZ4Gst35g9_BB3j2fUkRNZHZp3AAIMHAACLHLQVt0p7bTiHEOFOwQ	8178120332	59242	1	2026-04-11 13:47:23.22886+08
28	-1003883297177	BQACAgUAAyEFAATndmmZAAICP2nZ4M4FfuHAu1YbBZv2pDzkv68-AALiHQACzDvRVg98Rtt5D72QOwQ	7163866386	55516	1	2026-04-11 13:49:02.565968+08
29	-1003883297177	AgACAgUAAyEFAATndmmZAAICQWnZ4S8qI3tA3PFYM0yWzkhK3OfiAALDD2sbzDvRVuWIMgtGR8p9AQADAgADeQADOwQ	8642653065	74322	1	2026-04-11 13:50:39.13177+08
30	-1003883297177	AgACAgUAAyEFAATndmmZAAICQ2nZ4fdpDcrg2if_C8CPzDY6fWiPAALED2sbzDvRVkmkRGi-pL-RAQADAgADeQADOwQ	8580988163	74114	1	2026-04-11 13:53:58.986435+08
31	-1003883297177	AgACAgUAAyEFAATndmmZAAICTWnaYkPnX8C_IHsgG-CBLyPy1RLtAAK_EWsbzDvRVsXSlyDxBRMeAQADAgADeQADOwQ	8352461288	72494	1	2026-04-11 23:01:36.735425+08
32	-1003883297177	AgACAgUAAyEFAATndmmZAAICT2naYmWHMl_9xJQYPefi7WuZ0iiRAALAEWsbzDvRVkvQaSImQfGWAQADAgADeQADOwQ	8763615403	74314	1	2026-04-11 23:02:12.27486+08
33	-1003883297177	AgACAgUAAyEFAATndmmZAAICUWnaYoIThiRqtlz_Z3eroLnR3UvDAALBEWsbzDvRVgRYlgkT_hz5AQADAgADeQADOwQ	7736673658	29337	1	2026-04-11 23:02:26.198015+08
34	-1003883297177	BQACAgUAAyEFAATndmmZAAICU2naYo_Y96obEBdZ6_Nv7bhEvnihAAJoHwACzDvRVqen6n3EePO6OwQ	7625201169	56773	1	2026-04-11 23:02:38.828435+08
35	-1003883297177	BQACAgUAAyEFAATndmmZAAICVWnaYremcGGLivXNOXZXCyrfSZkJAAJpHwACzDvRVnTC46baBOhBOwQ	7163866386	55516	1	2026-04-11 23:03:19.111731+08
36	-1003883297177	BQACAgUAAyEFAATndmmZAAICV2naYvJPkJaBYc_O_HRxGlv1QcgiAAJqHwACzDvRVtbCE-BA_iuiOwQ	8233548675	72357	1	2026-04-11 23:04:18.26972+08
37	-1003883297177	AgACAgUAAyEFAATndmmZAAICWWnaYwVwXQABvhLFnh8K8HQeErqjGQACwhFrG8w70VbpJpiPOVw4IAEAAwIAA3kAAzsE	8590155218	74168	1	2026-04-11 23:04:37.146695+08
38	-1003883297177	AgACAgUAAyEFAATndmmZAAICW2naYxHRdsfiZ-IqlegZydA4_08WAALDEWsbzDvRVv7g6Rcip9feAQADAgADeQADOwQ	7074207060	58073	1	2026-04-11 23:04:48.768+08
39	-1003883297177	BQACAgUAAyEFAATndmmZAAICXWnaY0DswtBQtQZFARiPlXUc6vPKAAJrHwACzDvRVpzkOhKxSnWMOwQ	6562376911	17025	1	2026-04-11 23:05:36.65755+08
40	-1003883297177	BQACAgUAAyEFAATndmmZAAICX2naY2R-uOiptFmpZymTjEm3WAWDAALSHQACLHLQVj9kSxra72roOwQ	8178120332	59242	1	2026-04-11 23:06:11.651236+08
41	-1003883297177	AgACAgUAAyEFAATndmmZAAICYWnaY2dZCFCr6jfYVx8NilyI0BGHAALEEWsbzDvRVrw-nt7ffyIqAQADAgADeQADOwQ	8580988163	74114	1	2026-04-11 23:06:15.116718+08
42	-1003883297177	BQACAgUAAyEFAATndmmZAAICY2naY4dhbJxOMETr7Lxa7395c0LrAAJsHwACzDvRVhz0ch4Rd8nWOwQ	7056750099	4257	1	2026-04-11 23:06:46.639535+08
43	-1003883297177	AgACAgUAAyEFAATndmmZAAICZWnaY8evImJWEVFWZzgc5d45q9FtAALFEWsbzDvRVs4IaefSoJ1UAQADAgADeQADOwQ	7625966687	56753	1	2026-04-11 23:07:51.067797+08
44	-1003883297177	AgACAgUAAyEFAATndmmZAAICaGnaZtVMJ_w8dXEXZDKKgko4jW_BAALNEWsbzDvRVuTJ6T3emgICAQADAgADeQADOwQ	8642653065	74322	1	2026-04-12 02:23:57.794156+08
45	-1003883297177	AgACAgUAAyEFAATndmmZAAICZ2naZe1BeyH6WGrVGbLb_oI2xoxzAALMEWsbzDvRVv9nXZbyTlu8AQADAgADeQADOwQ	8532682955	74306	1	2026-04-12 02:23:57.900886+08
46	-1003767543777	AgACAgUAAyEFAATgkCfhAAIC6GnZFKrZUBa78ZAhGWulNutg1aYiAAJiDGsbLFjIVr5fEp1Xw1HzAQADAgADeQADOwQ	6332760420	7122	0	2026-04-12 02:32:25.328037+08
47	-1003883297177	AgACAgUAAyEFAATndmmZAAICbWnbJGnbvFSmgRkOdlE2FOMqMe8LAAKHDWsbzDvZVjUpg0tM8zbuAQADAgADeQADOwQ	8352461288	72494	1	2026-04-12 12:49:58.296105+08
48	-1003883297177	BQACAgUAAyEFAATndmmZAAICb2nbLMcvr2w3ifkW5odehuoMmx65AAKeIAACzDvZVjKnmOjX6eyFOwQ	6562376911	17025	1	2026-04-12 13:25:27.378269+08
49	-1003883297177	AgACAgUAAyEFAATndmmZAAICcWnbLnB9C3cYvHwpwLVieTtD-2RGAAKODWsbzDvZVppd_ugRIRlZAQADAgADeQADOwQ	7625966687	56753	1	2026-04-12 13:32:32.894783+08
50	-1003883297177	BQACAgUAAyEFAATndmmZAAICc2nbLoKK7xrv0HzxulJFjArpS-KKAAKjIAACzDvZVibj008luvAVOwQ	7056750099	4257	1	2026-04-12 13:32:50.469086+08
51	-1003883297177	BQACAgUAAyEFAATndmmZAAICdWnbLpaqN0G5pNHwzwhoJBwhgOuHAAKkIAACzDvZVvwLw1_rXvoWOwQ	7625201169	56773	1	2026-04-12 13:33:10.350949+08
52	-1003883297177	AgACAgUAAyEFAATndmmZAAICd2nbL3kFoAHGWZipE3ySCNfbDwN5AAKPDWsbzDvZVjfoFMFGjeyjAQADAgADeQADOwQ	8580988163	74114	1	2026-04-12 13:36:57.070498+08
53	-1003883297177	AgACAgUAAyEFAATndmmZAAICeWnbMN429yiVkI0yxtlCTiQUVeARAAKRDWsbzDvZVlyxiO0yu76oAQADAgADeQADOwQ	7736673658	29337	1	2026-04-12 13:42:54.092815+08
54	-1003883297177	AgACAgUAAyEFAATndmmZAAICe2nbMQdBBEHHDTy-cgp862ceNxNWAAKSDWsbzDvZVrfiwL2q9BCKAQADAgADeQADOwQ	8532682955	74306	1	2026-04-12 13:43:35.706494+08
55	-1003883297177	BQACAgUAAyEFAATndmmZAAICfWnbMRpu9GITnT2Bm4vpxX8--6h-AAKpIAACzDvZViy5B2_IKC0EOwQ	8233548675	72357	1	2026-04-12 13:43:54.423602+08
56	-1003883297177	AgACAgUAAyEFAATndmmZAAICf2nbMbwpBQVA4m4GKMYyNjpPup6cAAKVDWsbzDvZVv9GujYenp7GAQADAgADeQADOwQ	8590155218	74168	1	2026-04-12 13:46:36.269862+08
57	-1003883297177	BQACAgUAAyEFAATndmmZAAICgWnbMc15C6B7li-UaeCBHR3V6YeWAALIHQACLHLYVt3Su27SJiH6OwQ	8178120332	59242	1	2026-04-12 13:46:53.039117+08
58	-1003883297177	BQACAgUAAyEFAATndmmZAAICg2nbMdtlXnzD-6BsPkXvub88lDcrAAKqIAACzDvZVqbwU1DSZAYMOwQ	8157802833	56759	1	2026-04-12 13:47:07.703564+08
59	-1003883297177	AgACAgUAAyEFAATndmmZAAIChWnbMgXqqfhn_4L3zkBIJ4pfASqjAAKYDWsbzDvZVjYP-lvJ_vVnAQADAgADeQADOwQ	7074207060	58073	1	2026-04-12 13:47:49.242511+08
60	-1003883297177	AgACAgUAAyEFAATndmmZAAICh2nbMhPAXK7vScBsdvJIDFGGrs0-AAKZDWsbzDvZVvsn-8c6NBpEAQADAgADeQADOwQ	8763615403	74314	1	2026-04-12 13:48:18.632596+08
61	-1003883297177	BQACAgUAAyEFAATndmmZAAICiWnbMjvLOJdOzxeeaA2EtpFbS5VRAAKrIAACzDvZVoyjuEnAhLnPOwQ	7163866386	55516	1	2026-04-12 13:48:43.306996+08
62	-1003883297177	BQACAgUAAyEFAATndmmZAAICi2nbMqIroQWiuyZMtpXUMTv2HWkqAALsHwADUdlWXiQaWQFQv5Q7BA	7510241572	31088	1	2026-04-12 13:50:26.659587+08
63	-1003883297177	BQACAgUAAyEFAATndmmZAAICjWnbMwi6Fn2vgunEb0SgR-Vl5IQ2AAKtIAACzDvZVs72qzHicaclOwQ	6886314602	16908	1	2026-04-12 13:52:08.601506+08
64	-1003883297177	AgACAgUAAyEFAATndmmZAAICj2nbMxrrf2mTTqHHzL7omq5o4jbPAAKcDWsbzDvZVrs85S8AAfkO_AEAAwIAA3kAAzsE	8642653065	74322	1	2026-04-12 13:52:26.880663+08
65	-1003883297177	BQACAgUAAyEFAATndmmZAAIComnbs83-MM7C9dy8jvQ19_6gCAPsAAICIQACvx_gVoZYadG900iZOwQ	6562376911	17025	1	2026-04-12 23:01:33.445664+08
66	-1003883297177	BQACAgUAAyEFAATndmmZAAICpGnbs-yOl-Vr2_PjmqAqUovrsRYUAAIEIQACvx_gViVVmEsHMt4qOwQ	7163866386	55516	1	2026-04-12 23:02:03.834296+08
67	-1003883297177	BQACAgUAAyEFAATndmmZAAICpmnbs_Mkl74F6OTtIZZxljLolnXdAAIFIQACvx_gVqy2dcp6idVYOwQ	7625201169	56773	1	2026-04-12 23:02:11.2222+08
68	-1003883297177	BQACAgUAAyEFAATndmmZAAICqGnbtB9BWCUG5OwwgqSzNYEi6xkqAAIIIQACvx_gVjZY1oVVib1wOwQ	8157802833	56759	1	2026-04-12 23:02:54.533833+08
69	-1003883297177	AgACAgUAAyEFAATndmmZAAICqmnbtCBR1SRxbyq6kleeG9DBIkArAAKCEGsbvx_gVqqen8mUoTgyAQADAgADeQADOwQ	7074207060	58073	1	2026-04-12 23:02:56.035369+08
70	-1003883297177	BQACAgUAAyEFAATndmmZAAICrGnbtEOLvyHTrgcTdwh6rscwbVYEAAKUGwACjtvgVvmHx9BJlgQ5OwQ	8178120332	59242	1	2026-04-12 23:03:30.571479+08
71	-1003883297177	BQACAgUAAyEFAATndmmZAAICrmnbtJTzjXG-WXBJV-FE99cxsL0pAAIJIQACvx_gVryGDXXh419pOwQ	8233548675	72357	1	2026-04-12 23:04:52.292537+08
72	-1003883297177	BQACAgUAAyEFAATndmmZAAICsGnbtM2tQyRFJVpSYM94ZzAeRThHAAKLHwAC7VbYVqFHQB19e7AmOwQ	7510241572	31088	1	2026-04-12 23:05:48.433534+08
73	-1003883297177	BQACAgUAAyEFAATndmmZAAICsmnbtPWldJQHFll1wl3vvrMsXZy-AAIMIQACvx_gVuP2e2I3-4oIOwQ	6886314602	16908	1	2026-04-12 23:06:29.070705+08
74	-1003883297177	AgACAgUAAyEFAATndmmZAAICtGnbtRY_fZGCwo2zunSWdXa4EYz7AAKEEGsbvx_gVhNR4CAsBVURAQADAgADeQADOwQ	8580988163	74114	1	2026-04-12 23:07:01.882499+08
75	-1003883297177	BQACAgUAAyEFAATndmmZAAICt2nbtiezINzThMpbl3n5Pnm488y3AAINIQACvx_gVnaiq0Tu9ShCOwQ	7056750099	4257	1	2026-04-12 23:11:35.507657+08
76	-1003883297177	AgACAgUAAyEFAATndmmZAAICuWnbtl5VZt2MZNFbn5rkEWGrfPnkAAKHEGsbvx_gVkCfb8pUzH_bAQADAgADeQADOwQ	7625966687	56753	1	2026-04-12 23:12:29.542171+08
77	-1003883297177	AgACAgUAAyEFAATndmmZAAICu2nbtmbsGAFzxd_ZqZ3CRW2dqAOcAAKIEGsbvx_gVpjfp9uXwhDrAQADAgADeQADOwQ	8590155218	74168	1	2026-04-12 23:12:37.634901+08
78	-1003883297177	AgACAgUAAyEFAATndmmZAAICvWnbtpiqCXNw22yRtexvGt4lLsYOAAKJEGsbvx_gVvNZ9xwU16F8AQADAgADeQADOwQ	8532682955	74306	1	2026-04-12 23:13:28.252398+08
79	-1003883297177	AgACAgUAAyEFAATndmmZAAICv2nbttiDEgAByXoVNbpIZZUDDwdIFgACixBrG78f4Fbim7uNW60mfgEAAwIAA3kAAzsE	7736673658	29337	1	2026-04-12 23:14:31.736325+08
80	-1003883297177	AgACAgUAAyEFAATndmmZAAICwWnbuch_bsiToUjpLCxPOuCDSPx-AAKQEGsbvx_gVgT5tsA-9m1PAQADAgADeQADOwQ	8763615403	74314	1	2026-04-12 23:27:17.757313+08
81	-1003883297177	AgACAgUAAyEFAATndmmZAAICw2nbuusCJXGkE-solB98XCk44LdzAAKUEGsbvx_gVrrDbsrUSpv5AQADAgADeQADOwQ	8352461288	72494	1	2026-04-12 23:32:07.073555+08
82	-1003883297177	AgACAgUAAyEFAATndmmZAAICxWnbvn-UPwLWB_ADAbyyZoBPl3lcAAKmEGsbvx_gVv4j3WeNZ-aQAQADAgADeQADOwQ	8642653065	74322	1	2026-04-12 23:47:11.611377+08
83	-1003883297177	AgACAgUAAyEFAATndmmZAAICyWncfDNcZ6M6fWTvYY9BAuMdNr4iAAKhDmsbvx_oVtJQhQs54Aq6AQADAgADeQADOwQ	8763615403	74314	1	2026-04-13 13:16:51.299017+08
84	-1003883297177	AgACAgUAAyEFAATndmmZAAICy2ncfZXf0rlRWc_GDAMJ9W88Js5LAAKmDmsbvx_oVnHjvNvlMvlAAQADAgADeQADOwQ	8532682955	74306	1	2026-04-13 13:22:29.840893+08
85	-1003883297177	AgACAgUAAyEFAATndmmZAAICzWncgBqqGEQuBn-hH28Iv4SX0VLyAAJdDmsbZLW5VswHKc_aayLSAQADAgADeQADOwQ	8352461288	72494	1	2026-04-13 13:33:13.940066+08
86	-1003883297177	BQACAgUAAyEFAATndmmZAAICz2ncgC4BpP5nLSqpA3wNsp8BP01YAAMjAAK_H-hWvpywTK8UqF87BA	7056750099	4257	1	2026-04-13 13:33:34.832275+08
87	-1003883297177	BQACAgUAAyEFAATndmmZAAIC0WncgJFn3DA6Z-orXA2MXe9YwxbpAAIDIwACvx_oVnqrS-JVS3JlOwQ	7625201169	56773	1	2026-04-13 13:35:13.22445+08
88	-1003883297177	BQACAgUAAyEFAATndmmZAAIC02ncgLMVE7r5pTxp24yQvbU3vv5vAAIFIwACvx_oVjKBrBiq7OCUOwQ	6562376911	17025	1	2026-04-13 13:35:47.425418+08
89	-1003883297177	BQACAgUAAyEFAATndmmZAAIC1WncghcjH-d4BWjHTSP4u3C54D50AAIOIwACvx_oVjtQth1l-o89OwQ	8233548675	72357	1	2026-04-13 13:41:43.389437+08
90	-1003883297177	AgACAgUAAyEFAATndmmZAAIC12ncgmZa70oNGUi7b6_zbK9vty2VAAK5Dmsbvx_oVmWNs238ln07AQADAgADeQADOwQ	7736673658	29337	1	2026-04-13 13:43:02.115242+08
91	-1003883297177	AgACAgUAAyEFAATndmmZAAIC2WncgpynzPXdMCrstrgjZubGBC3zAAK6Dmsbvx_oVhvBpylNOsRiAQADAgADeQADOwQ	7074207060	58073	1	2026-04-13 13:43:56.868152+08
92	-1003883297177	AgACAgUAAyEFAATndmmZAAIC22ncg2VHGBbb3CRibGDgxwHjsoKyAAK_Dmsbvx_oVlGBWVaaFczkAQADAgADeQADOwQ	8580988163	74114	1	2026-04-13 13:47:16.97253+08
93	-1003883297177	AgACAgUAAyEFAATndmmZAAIC3Wncg2ssRggJ9VYy5dt8yY7DN0hXAALADmsbvx_oVgJlhNH_j_8cAQADAgADeQADOwQ	7625966687	56753	1	2026-04-13 13:47:23.299253+08
94	-1003883297177	BQACAgUAAyEFAATndmmZAAIC32ncg_Xrb4_uZW_0qPh-owEAAftDFAACESMAAr8f6FadJXAQ3_arCTsE	7163866386	55516	1	2026-04-13 13:49:41.392514+08
95	-1003883297177	AgACAgUAAyEFAATndmmZAAIC4WnchAReG-TdXHC5BqHSGSFZzn4yAALDDmsbvx_oVu6pYPXReaWRAQADAgADeQADOwQ	8642653065	74322	1	2026-04-13 13:49:56.445989+08
96	-1003883297177	BQACAgUAAyEFAATndmmZAAIC42nchBDRwXATn2_ByDIBEvLeWULfAAKcHQAC7VbgVv6NboaXUNfHOwQ	7510241572	31088	1	2026-04-13 13:50:09.007186+08
97	-1003883297177	BQACAgUAAyEFAATndmmZAAIC5WnchGsUQIV1mxxTXmQfqSFAkw_WAAITIwACvx_oVtuvQ4qDc8SUOwQ	6886314602	16908	1	2026-04-13 13:51:39.582652+08
98	-1003883297177	BQACAgUAAyEFAATndmmZAAIC52nchHCN1AJ06BLpdvEW2NqlgDT3AAKTHAACjtvgVi4_SqDTUHHcOwQ	8178120332	59242	1	2026-04-13 13:51:43.919303+08
99	-1003883297177	BQACAgUAAyEFAATndmmZAAIC6WnchMHBCDRldA2TkE5ScYvlyANMAAIVIwACvx_oVrU3K6cb0fFnOwQ	8157802833	56759	1	2026-04-13 13:53:05.998268+08
100	-1003883297177	AgACAgUAAyEFAATndmmZAAIC62nchdn1nPnzFUINk6IvdIYEaCKFAALLDmsbvx_oVjKpIYWcqiSBAQADAgADeQADOwQ	8590155218	74168	1	2026-04-13 13:57:45.83834+08
101	-1003883297177	BQACAgUAAyEFAATndmmZAAIDDGndBUOxVSCTJtczuE16pAFJrUVMAAJAJQACvx_oVmMow9LTZT7yOwQ	7163866386	55516	1	2026-04-13 23:01:23.403488+08
102	-1003883297177	BQACAgUAAyEFAATndmmZAAIDDmndBUnpH9CZTb0m1Pf6cSIMPS2tAAJDJQACvx_oVuWe9sEj67O_OwQ	7056750099	4257	1	2026-04-13 23:01:29.269443+08
103	-1003883297177	AgACAgUAAyEFAATndmmZAAIDEGndBVFwAuvMRiS_WH54Sl-FxbtFAAJrEGsbvx_oVsvwpRtJDvnCAQADAgADeQADOwQ	7736673658	29337	1	2026-04-13 23:01:36.650513+08
104	-1003883297177	BQACAgUAAyEFAATndmmZAAIDE2ndBWxyIU0KoiTEsPrN3qe3pqHxAAJJJQACvx_oVsGpDbnGlQuNOwQ	6562376911	17025	1	2026-04-13 23:02:03.570423+08
105	-1003883297177	AgACAgUAAyEFAATndmmZAAIDFWndBXk8V_iyKw7IcYNUDBvI_MgdAAJsEGsbvx_oVi5EKCYvSujhAQADAgADeQADOwQ	8763615403	74314	1	2026-04-13 23:02:17.115077+08
106	-1003883297177	BQACAgUAAyEFAATndmmZAAIDF2ndBYoefezdmTzM934LLrIk-mrGAALyHAACjtvoVrpoyikiPY_EOwQ	8178120332	59242	1	2026-04-13 23:02:33.924779+08
107	-1003883297177	BQACAgUAAyEFAATndmmZAAIDGWndBY8SLvGdJUmpWK0L8FDvilyYAAJNJQACvx_oVgXUrLSU8t_3OwQ	6886314602	16908	1	2026-04-13 23:02:38.825783+08
108	-1003883297177	AgACAgUAAyEFAATndmmZAAIDG2ndBak8Dgb9iBr8pQd5gKFXnVuTAAJtEGsbvx_oVgojmTvoGPHmAQADAgADeQADOwQ	7074207060	58073	1	2026-04-13 23:03:04.982096+08
109	-1003883297177	BQACAgUAAyEFAATndmmZAAIDGWndBcqOCYQr_NTc1MfsEDBhOgaQAAJSJQACvx_oVpdpmH7ZEadPOwQ	6886314602	16908	1	2026-04-13 23:03:39.357538+08
110	-1003883297177	BQACAgUAAyEFAATndmmZAAIDIGndBdOJMV2uJXWUe2GpXdzrZ0GJAAJMHwAC7VboVpF5UKlqt3J7OwQ	7510241572	31088	1	2026-04-13 23:03:46.923367+08
111	-1003883297177	BQACAgUAAyEFAATndmmZAAIDI2ndBi4bzZNyxCAnvUrGDKjOtQi8AAJTJQACvx_oVnU93cnQTscuOwQ	8233548675	72357	1	2026-04-13 23:05:18.36799+08
112	-1003883297177	BQACAgUAAyEFAATndmmZAAIDJWndBmrVhMRNCBEJTAvOUBwgTyhEAAJUJQACvx_oViUiI4YscMHcOwQ	8157802833	56759	1	2026-04-13 23:06:18.311818+08
113	-1003883297177	AgACAgUAAyEFAATndmmZAAIDJ2ndBvJKyqI1x-GaEVPtd_JdjFteAAJxEGsbvx_oVskQCnMn1V9pAQADAgADeQADOwQ	7625966687	56753	1	2026-04-13 23:08:33.711571+08
114	-1003883297177	AgACAgUAAyEFAATndmmZAAIDKmndB7zcKUQgK0QE4HUrk68fTHZOAAJ0EGsbvx_oVs8HQWFyff1GAQADAgADeQADOwQ	8580988163	74114	1	2026-04-13 23:11:56.223976+08
115	-1003883297177	AgACAgUAAyEFAATndmmZAAIDLGndCEkLG0x4da_82VmK8ks4EygTAAJ3EGsbvx_oVqdaQ0k1_Xe8AQADAgADeQADOwQ	7625201169	56773	1	2026-04-13 23:14:17.313395+08
116	-1003883297177	AgACAgUAAyEFAATndmmZAAIDLmndCMpa1yfQ8X96c2cCZlV7-rDOAAJ5EGsbvx_oVgcdPOmvH3NiAQADAgADeQADOwQ	8590155218	74168	1	2026-04-13 23:16:25.682754+08
117	-1003883297177	AgACAgUAAyEFAATndmmZAAIDMGndCqDjP60_XcxhxSnw-ib_wxL_AAJ9EGsbvx_oVjDycV8tdXkXAQADAgADeQADOwQ	8352461288	72494	1	2026-04-13 23:24:36.921721+08
118	-1003883297177	AgACAgUAAyEFAATndmmZAAIDMmndDJlm1UYq1vh80evXRapFFdPtAAKAEGsbvx_oVruakF16OMbYAQADAgADeQADOwQ	8532682955	74306	1	2026-04-13 23:32:41.429708+08
119	-1003883297177	AgACAgUAAyEFAATndmmZAAIDNGndD2wBX05UnlplrsOZP2tao-11AAKLEGsbvx_oVuG0cW3rFGAiAQADAgADeQADOwQ	8642653065	74322	1	2026-04-13 23:44:43.583419+08
120	-1003883297177	AgACAgUAAyEFAATndmmZAAIDOGnd0Pjks4jqTtCZcjLgMFWNNycvAAK0DWsbzZnxVs1e-oXIpSsxAQADAgADeQADOwQ	7736673658	29337	1	2026-04-14 13:30:32.198312+08
121	-1003883297177	AgACAgUAAyEFAATndmmZAAIDOmnd0TAOtyQRHQ2F_DeDOlPNzP3iAAK1DWsbzZnxViFHUBrb2f0uAQADAgADeQADOwQ	8532682955	74306	1	2026-04-14 13:31:29.357944+08
122	-1003883297177	BQACAgUAAyEFAATndmmZAAIDPGnd0eFEE1Lrj46jW50AAfFma42XsgACZBoAAs2Z8Vb9fCR0gouwzDsE	7056750099	4257	1	2026-04-14 13:34:25.450191+08
123	-1003883297177	BQACAgUAAyEFAATndmmZAAIDPmnd0iJ2JCJpDNx4OVhn2fPRfpQ_AAJlGgACzZnxVj8Jfp5eQehfOwQ	7625201169	56773	1	2026-04-14 13:35:32.326157+08
124	-1003883297177	AgACAgUAAyEFAATndmmZAAIDQGnd0jwWXS1FAAE2VRcltKNhgKnuNgACtg1rG82Z8Va9tCzrvG9LnAEAAwIAA3kAAzsE	8590155218	74168	1	2026-04-14 13:35:56.567034+08
125	-1003883297177	BQACAgUAAyEFAATndmmZAAIDQmnd1JDL7_5WCuvvLb1cmAIExPFIAAJnGgACzZnxVjWACI3PQ5ZpOwQ	8157802833	56759	1	2026-04-14 13:45:52.586892+08
126	-1003883297177	BQACAgUAAyEFAATndmmZAAIDRGnd1PIjpY0Gf99NrAVyU6xn7wABBAACaRoAAs2Z8VZqNk8eKPaI7zsE	6562376911	17025	1	2026-04-14 13:47:30.740555+08
127	-1003883297177	AgACAgUAAyEFAATndmmZAAIDRmnd1RBbAsizC6LAuU7BOlDOsJOaAAK5DWsbzZnxVsUjePAatPaHAQADAgADeQADOwQ	7074207060	58073	1	2026-04-14 13:48:00.953518+08
128	-1003883297177	AgACAgUAAyEFAATndmmZAAIDRmnd1RBbAsizC6LAuU7BOlDOsJOaAAK5DWsbzZnxVsUjePAatPaHAQADAgADeQADOwQ	7074207060	58073	1	2026-04-14 13:48:19.975675+08
129	-1003883297177	BQACAgUAAyEFAATndmmZAAIDSWnd1UlKiRBg7uE6XamLhJXUuQABNgACahoAAs2Z8VamM4Nmhr0h2jsE	7163866386	55516	1	2026-04-14 13:48:57.89531+08
130	-1003883297177	BQACAgUAAyEFAATndmmZAAIDS2nd1YzPZesRWsMq_hpEqvki_gqYAAKLHgAC4ejwVgGvQMb-tDWoOwQ	7510241572	31088	1	2026-04-14 13:50:04.858779+08
131	-1003883297177	AgACAgUAAyEFAATndmmZAAIDTWnd1dJ3KRLLcc-XRkNNgjmxEapXAAK6DWsbzZnxVm0KII4HQ6-PAQADAgADeQADOwQ	7625966687	56753	1	2026-04-14 13:51:14.320836+08
132	-1003883297177	BQACAgUAAyEFAATndmmZAAIDT2nd1d_k0QdR27gWtGGuHLROEclAAAJrGgACzZnxVs-o_kmnzfGNOwQ	6886314602	16908	1	2026-04-14 13:51:27.420219+08
133	-1003883297177	AgACAgUAAyEFAATndmmZAAIDUmnd1kO_SDyBAAH6vN-pZV7KVLVEVQACuw1rG82Z8VZZhssfBXQy2wEAAwIAA3kAAzsE	8352461288	72494	1	2026-04-14 13:53:19.934136+08
134	-1003883297177	AgACAgUAAyEFAATndmmZAAIDVGnd18beIaYpJwNbY5R13Jld7OD6AAK9DWsbzZnxVrTdr9g7MiyAAQADAgADeQADOwQ	8580988163	74114	1	2026-04-14 13:59:34.67675+08
135	-1003883297177	BQACAgUAAyEFAATndmmZAAIDXWneVszt9gLKORwHSciXW0f3ehtXAAIEHAACzZnxVt7QVZr0wSiuOwQ	7163866386	55516	1	2026-04-14 23:01:32.343803+08
136	-1003883297177	BQACAgUAAyEFAATndmmZAAIDX2neVvBYo7msvekb98XQe1NaRuPxAAIFHAACzZnxVsfOtymcD1kZOwQ	6562376911	17025	1	2026-04-14 23:02:08.56757+08
137	-1003883297177	BQACAgUAAyEFAATndmmZAAIDYWneVw72iriflIZoODpSzp1es1KCAAIGHAACzZnxVsHwYmQpcFylOwQ	7625201169	56773	1	2026-04-14 23:02:38.087443+08
138	-1003883297177	AgACAgUAAyEFAATndmmZAAIDY2neVynE-bFQNxe2OWrBOoiBfcwHAAKeDmsbzZnxVgXQi_VmUcOWAQADAgADeQADOwQ	8590155218	74168	1	2026-04-14 23:03:05.037688+08
139	-1003883297177	BQACAgUAAyEFAATndmmZAAIDZWneV03cUnjwA6dJnlinHsZNq9UhAAIHHAACzZnxVpZcdGr4HjU4OwQ	6886314602	16908	1	2026-04-14 23:03:41.429262+08
140	-1003883297177	AgACAgUAAyEFAATndmmZAAIDaGneV31tzVcAAVOWWSu5dSiZwKQUPAACnw5rG82Z8VYGlp2FsRYI2AEAAwIAA3kAAzsE	7074207060	58073	1	2026-04-14 23:04:28.752768+08
141	-1003883297177	BQACAgUAAyEFAATndmmZAAIDamneV8WQG3pWlGl77eTsGbeXMaLkAAIIHAACzZnxVs3hzR2Q4ksYOwQ	7056750099	4257	1	2026-04-14 23:05:41.532624+08
142	-1003883297177	AgACAgUAAyEFAATndmmZAAIDbGneV9NznYJO6cgBSgy5pHfou440AAKgDmsbzZnxVtK-mlWrCYDCAQADAgADeQADOwQ	8580988163	74114	1	2026-04-14 23:05:55.058309+08
143	-1003883297177	BQACAgUAAyEFAATndmmZAAIDbmneWAgzQ0gME7aqjSODASc0gECLAALxIgAC4ej4VhSartnCQZSpOwQ	7510241572	31088	1	2026-04-14 23:06:47.740684+08
144	-1003883297177	AgACAgUAAyEFAATndmmZAAIDcGneWBcMWMjKgeVifXZ608xrevCXAAKhDmsbzZnxVnSwpzvawOKvAQADAgADeQADOwQ	7736673658	29337	1	2026-04-14 23:07:03.020939+08
145	-1003883297177	BQACAgUAAyEFAATndmmZAAIDcmneWG9HndqEsNiP59nhlDZb25YFAAIKHAACzZnxVjTbcKbXXfUBOwQ	8157802833	56759	1	2026-04-14 23:08:31.195927+08
146	-1003883297177	AgACAgUAAyEFAATndmmZAAIDdGneWk3ChLceOW-ASHifTyDgQb8EAAKkDmsbzZnxVgtpuZKnEDsXAQADAgADeQADOwQ	7625966687	56753	1	2026-04-14 23:16:28.815152+08
147	-1003883297177	AgACAgUAAyEFAATndmmZAAIDeGneZLVsNi2tuutp1j4W63_SDs8LAAK-DmsbzZnxVq0kZQVykhBhAQADAgADeQADOwQ	8352461288	72494	1	2026-04-15 00:01:04.324026+08
148	-1003883297177	AgACAgUAAyEFAATndmmZAAID_mnjnWmZvMK12yRrD7hNLRmKdHtZAAK-EWsb0wkgV8krrLzqH-heAQADAgADeQADOwQ	8763615403	74314	1	2026-04-19 14:32:46.011689+08
149	-1003883297177	AgACAgUAAyEFAATndmmZAAIEBmnjpJMNzK7wGvpTuglAgJ3TEmelAALbEWsb0wkgV-isNbwDUL0WAQADAgADeQADOwQ	8352461288	72494	1	2026-04-19 14:32:46.113344+08
150	-1003883297177	AgACAgUAAyEFAATndmmZAAIECmnkYrtc_CmrSorGtWf6Mg0HoRfdAALVD2sb0wkoV7aZwdPiy9-JAQADAgADeQADOwQ	8352461288	72494	1	2026-04-19 14:32:46.217576+08
151	-1003883297177	AgACAgUAAyEFAATndmmZAAIEEmnka-Nwv0KHc3fFO0gBC_nQ9WvHAALsD2sb0wkoVylCc3LAsppdAQADAgADeQADOwQ	8763615403	74314	1	2026-04-19 14:32:46.447038+08
152	-1003883297177	AgACAgUAAyEFAATndmmZAAIEEGnkawe0QVgvDEup_4XXDDAUKe3EAALpD2sb0wkoV3xKQ9H7MOfqAQADAgADeQADOwQ	7736673658	29337	1	2026-04-19 14:32:46.655419+08
153	-1003883297177	BQACAgUAAyEFAATndmmZAAID-2njnT04_6aTjFqhaqzhksmC2E8RAAInHgAC0wkgV7V11zVoY2WEOwQ	7163866386	55516	1	2026-04-19 14:32:46.917432+08
154	-1003883297177	BQACAgUAAyEFAATndmmZAAID_GnjnV2wwgvkTrKdsJ-8SkKAmXrNAAJRHgACQpgZVzpuFFl3LboQOwQ	7510241572	31088	1	2026-04-19 14:32:47.017078+08
155	-1003883297177	AgACAgUAAyEFAATndmmZAAID_WnjnWH_wdcc9VfhmX-cn0IeGb-cAAK9EWsb0wkgV0OktG6GAAHvTQEAAwIAA3kAAzsE	8580988163	74114	1	2026-04-19 14:32:47.302158+08
156	-1003883297177	AgACAgUAAyEFAATndmmZAAID_2njnW4313ClWYCxmPK23yJc48snAAK_EWsb0wkgV8uFulpo6QAB8gEAAwIAA3kAAzsE	8590155218	74168	1	2026-04-19 14:32:47.41323+08
157	-1003883297177	BQACAgUAAyEFAATndmmZAAIEAAFp45113wxO3G-tIJKg7Mf1TB3gaAACKR4AAtMJIFcrN4bgbd-N6zsE	8233548675	72357	1	2026-04-19 14:32:47.519718+08
158	-1003883297177	BQACAgUAAyEFAATndmmZAAIEAmnjng7kpovdSChlDrEJSDIYfP3wAAIqHgAC0wkgVxXoxqu_hsoVOwQ	7056750099	4257	1	2026-04-19 14:32:47.618568+08
159	-1003883297177	AgACAgUAAyEFAATndmmZAAIEBGnjnrmAX5D4UiHbMOH4mPL9N5AgAALDEWsb0wkgV_3anUJ4WavxAQADAgADeQADOwQ	7736673658	29337	1	2026-04-19 14:32:47.722264+08
160	-1003883297177	AgACAgUAAyEFAATndmmZAAIECGnjqskBEB_xEsvsAAGkRM9rPTqtzAADEmsb0wkgV1aAZvjihewXAQADAgADeQADOwQ	8642653065	74322	1	2026-04-19 14:32:47.836358+08
161	-1003883297177	BQACAgUAAyEFAATndmmZAAIEB2njpbKXqi7v_U_ArbZFt2n7nO0cAAI9HgAC0wkgV8o5erVz0rI0OwQ	6562376911	17025	1	2026-04-19 14:32:47.944685+08
162	-1003883297177	AgACAgUAAyEFAATndmmZAAIEC2nkZpOcDdb-rZFbv4BQ-BFgqN1wAALgD2sb0wkoV5bvmmxuQVy7AQADAgADeQADOwQ	8532682955	74306	1	2026-04-19 14:32:48.051211+08
163	-1003883297177	AgACAgUAAyEFAATndmmZAAIEBWnjooCevs4asGEC7q3vV0WJgnGRAALXEWsb0wkgV7ID8jVkW2vmAQADAgADeQADOwQ	8532682955	74306	1	2026-04-19 14:32:48.153764+08
164	-1003883297177	AgACAgUAAyEFAATndmmZAAIECWnjzou21IWqRRkGhqz_b1xZqILpAAIxEmsb0wkgVxi3jJTymHvJAQADAgADeQADOwQ	7625966687	56753	1	2026-04-19 14:32:48.264402+08
165	-1003883297177	AgACAgUAAyEFAATndmmZAAIEA2njnifnJy2lLWAFOwUXsMKxqUHnAALCEWsb0wkgV7jjP0PdCBqkAQADAgADeQADOwQ	7074207060	58073	1	2026-04-19 14:32:48.358279+08
166	-1003883297177	BQACAgUAAyEFAATndmmZAAIEAWnjnbwbRI_rvMX4OSmT64U3RO7MAAJCIgACXnkhV9KtZszCcD8POwQ	8178120332	59242	1	2026-04-19 14:32:48.481211+08
167	-1003883297177	BQACAgUAAyEFAATndmmZAAIEEWnka0YxDu9ZsqZo88CGrg6TJYjOAAJUIwACXnkhVwRYW4M_YsIBOwQ	8178120332	59242	1	2026-04-19 14:32:48.583683+08
168	-1003883297177	AgACAgUAAyEFAATndmmZAAIEEGnkasM1pgG7eeogCYjpBFlk7qniAALoD2sb0wkoV1LD-mzWa-jhAQADAgADeQADOwQ	7736673658	29337	1	2026-04-19 14:32:48.917969+08
169	-1003883297177	BQACAgUAAyEFAATndmmZAAIEE2nkbB7iI2J60AsquicCKTr1gHJKAAJRHAAC0wkoV9wgA3Wn69VKOwQ	8233548675	72357	1	2026-04-19 14:32:49.035259+08
170	-1003883297177	BQACAgUAAyEFAATndmmZAAIEFGnkbNKMuHbjBEgsym7ssna9L_pJAAJYHAAC0wkoV-xe9zu3oC5vOwQ	7163866386	55516	1	2026-04-19 14:32:49.135623+08
171	-1003883297177	BQACAgUAAyEFAATndmmZAAIEDGnkZ-55ELTrLPz9rzO3cjUvhzzXAAIqHAAC0wkoVzc-pHhaVgPVOwQ	7625201169	56773	1	2026-04-19 14:32:49.240318+08
172	-1003883297177	BQACAgUAAyEFAATndmmZAAIEGWnkbn2JIFYJ0sbGqqg8aPWwW5KgAAJiHAAC0wkoV-3zRzpw2uy9OwQ	8157802833	56759	1	2026-04-19 14:32:49.459548+08
173	-1003883297177	AgACAgUAAyEFAATndmmZAAIEFmnkbRrpmQ78C2GETUjvOsX6cka-AALzD2sb0wkoVzQjiBYxNlbLAQADAgADeQADOwQ	7074207060	58073	1	2026-04-19 14:32:49.569278+08
174	-1003883297177	AgACAgUAAyEFAATndmmZAAIEGmnkbq_SKJBCEx7qYZrnBmMQAlcdAAL2D2sb0wkoVwmY0KpeqqhzAQADAgADeQADOwQ	7625966687	56753	1	2026-04-19 14:32:49.675952+08
175	-1003883297177	AgACAgUAAyEFAATndmmZAAIEDWnkaLIWWWKeZPVuvd5Sf4ux3OkfAALmD2sb0wkoVySLco7pwTqlAQADAgADeQADOwQ	8590155218	74168	1	2026-04-19 14:32:49.776127+08
176	-1003883297177	BQACAgUAAyEFAATndmmZAAIEDmnkaSyH6TI24Xh-FjngUsZ9zPf2AAItHAAC0wkoV_I6lrAjDgalOwQ	7056750099	4257	1	2026-04-19 14:32:49.977989+08
177	-1003883297177	BQACAgUAAyEFAATndmmZAAIEFWnkbPZbHazhTIqpAS9ICnsYN3_9AAKdHgACQpghV71IV_ZLRXFwOwQ	7510241572	31088	1	2026-04-19 14:32:50.082974+08
178	-1003883297177	BQACAgUAAyEFAATndmmZAAIEF2nkbcVGBDQq9VURwsmjeClj7WeJAAJbHAAC0wkoV-RSVQrsEiiIOwQ	6886314602	16908	1	2026-04-19 14:32:50.18869+08
179	-1003883297177	AgACAgUAAyEFAATndmmZAAIEG2nkb5ZZPQZJWA_ID54gCbmzmChUAAL4D2sb0wkoV9Oltr5884OXAQADAgADeQADOwQ	6562376911	17025	1	2026-04-19 14:32:50.299055+08
180	-1003883297177	AgACAgUAAyEFAATndmmZAAIED2nkabuKcPdMUNyazl_ontH0Mc3xAALnD2sb0wkoVzbs3JrWme7bAQADAgADeQADOwQ	8580988163	74114	1	2026-04-19 14:32:50.397111+08
181	-1003883297177	BQACAgUAAyEFAATndmmZAAIEKmnk7jY7jf3uxsy72PPvx08469hwAAIBHgAC0wkoV3-9PrFCD_sYOwQ	6562376911	17025	1	2026-04-19 23:01:10.725452+08
182	-1003883297177	BQACAgUAAyEFAATndmmZAAIELGnk7l_jQtSrPtke0owup92fhHvpAAIFHgAC0wkoV9lthGqBgkWfOwQ	8233548675	72357	1	2026-04-19 23:01:51.200978+08
183	-1003883297177	AgACAgUAAyEFAATndmmZAAIELmnk7neKRAetVGSevUTXqUFe8Bd9AALrEmsb0wkoVy3RVyRwjVZTAQADAgADeQADOwQ	8763615403	74314	1	2026-04-19 23:02:27.665596+08
184	-1003883297177	BQACAgUAAyEFAATndmmZAAIEMGnk7orQ1u5VP5LYcF8TSh4IHalAAAIIHgAC0wkoV58uplii02OkOwQ	7163866386	55516	1	2026-04-19 23:02:34.547581+08
185	-1003883297177	BQACAgUAAyEFAATndmmZAAIEMmnk7ou7Kb6v_fbL2NWVyLQqFtdAAAIJHgAC0wkoVxN6ruXPGnuLOwQ	7625201169	56773	1	2026-04-19 23:02:35.802614+08
186	-1003883297177	BQACAgUAAyEFAATndmmZAAIENGnk7psLd0a-n3FMg2f9y2hocdZ_AAL1HwACQpghV5ppvCNCMOwLOwQ	7510241572	31088	1	2026-04-19 23:02:50.930837+08
187	-1003883297177	AgACAgUAAyEFAATndmmZAAIEN2nk7sVzVGD2wt0MtZ8IqP8zkt2lAALtEmsb0wkoV5vWCHnPD3RFAQADAgADeQADOwQ	7074207060	58073	1	2026-04-19 23:03:33.246766+08
188	-1003883297177	BQACAgUAAyEFAATndmmZAAIEOWnk7vPXqqf7aY03h5oGMEnyJV1qAAJkHgACXnkpV2t7Aj3r0LVKOwQ	8178120332	59242	1	2026-04-19 23:04:19.047887+08
189	-1003883297177	AgACAgUAAyEFAATndmmZAAIEO2nk7w9sXLsQ22ciRJKGmmuLSw1MAALwEmsb0wkoV15WXeXxzpexAQADAgADeQADOwQ	8580988163	74114	1	2026-04-19 23:04:47.533943+08
190	-1003883297177	AgACAgUAAyEFAATndmmZAAIEPWnk73u4a7zpvNOQoUQAAbYa0K9fqAAC8hJrG9MJKFcf6xRZzIVzDAEAAwIAA3kAAzsE	7736673658	29337	1	2026-04-19 23:06:34.844124+08
191	-1003883297177	BQACAgUAAyEFAATndmmZAAIEP2nk75zfslD39_keOpC51ogEDzCYAAIPHgAC0wkoV5vERaQPO8cIOwQ	8157802833	56759	1	2026-04-19 23:07:07.926096+08
192	-1003883297177	AgACAgUAAyEFAATndmmZAAIEQWnk78wnffVQqc2qHRQHbWdcT-xZAALzEmsb0wkoV4Lc4WViNNaoAQADAgADeQADOwQ	8532682955	74306	1	2026-04-19 23:07:55.685786+08
193	-1003883297177	BQACAgUAAyEFAATndmmZAAIEQ2nk7-iL_ez_9r6GXEYKqhQxzN4vAAIRHgAC0wkoV5XLSYml9KNbOwQ	7056750099	4257	1	2026-04-19 23:08:24.41617+08
194	-1003883297177	AgACAgUAAyEFAATndmmZAAIERWnk8VEnU1Jy-8_DWCzHsHcGGdqPAAL4Emsb0wkoV7-zAAF_DWcLygEAAwIAA3kAAzsE	8590155218	74168	1	2026-04-19 23:14:24.713901+08
195	-1003883297177	AgACAgUAAyEFAATndmmZAAIER2nk8d3Hz6_UHBLe-gV71ubh0p0UAAL6Emsb0wkoV0w4K1b0-mXVAQADAgADeQADOwQ	6886314602	16908	1	2026-04-19 23:16:45.349115+08
196	-1003883297177	AgACAgUAAyEFAATndmmZAAIESWnk9J1wC2lnrng56NTgyRn0sCyFAAIHE2sb0wkoV5BONICtSaYpAQADAgADeQADOwQ	8642653065	74322	1	2026-04-19 23:28:29.152277+08
197	-1003883297177	AgACAgUAAyEFAATndmmZAAIES2nlBri9LdFEXoSBcS_on16jz9_9AAJSE2sb0wkoV-ovth1DnTtTAQADAgADeQADOwQ	8352461288	72494	1	2026-04-20 00:46:05.789216+08
198	-1003883297177	AgACAgUAAyEFAATndmmZAAIFrmnyKZJIw92TaPv5aMuh--pzN-fmAAJFD2sbO6-QV6wRoPbmhGmyAQADAgADeQADOwQ	8352461288	72494	1	2026-04-30 19:09:06.99908+08
199	-1003883297177	AgACAgUAAyEFAATndmmZAAIFr2ny40raowUoLHm0LhabWctiv1DkAAJvD2sbO6-YVyHLe1zG0JzxAQADAgADeQADOwQ	8352461288	72494	1	2026-04-30 19:09:07.102784+08
200	-1003883297177	AgACAgUAAyEFAATndmmZAAIFrmnyKZJIw92TaPv5aMuh--pzN-fmAAJFD2sbO6-QV6wRoPbmhGmyAQADAgADeQADOwQ	8352461288	72494	1	2026-04-30 19:09:07.333887+08
201	-1003883297177	AgACAgUAAyEFAATndmmZAAIFumny67yDj5-5zO4Q6agC0j5EGszDAAKCD2sbO6-YVyb4Ur4qeb4zAQADAgADeQADOwQ	8763615403	74314	1	2026-04-30 19:09:07.445204+08
202	-1003883297177	BQACAgUAAyEFAATndmmZAAIFomnyHbpxsazHCN-JPaJS_bT8E57vAAIHIAACO6-QV1iJ6GpJzTWfOwQ	6886314602	16908	1	2026-04-30 19:09:07.729778+08
203	-1003883297177	BQACAgUAAyEFAATndmmZAAIFpGnyHcD9Ul0OhOVoDFWJkp0rReemAAIIIAACO6-QV6K4VD8xTJ8pOwQ	7056750099	4257	1	2026-04-30 19:09:07.839767+08
204	-1003883297177	BQACAgUAAyEFAATndmmZAAIFpWnyHdBtZ5YU9p-nmRUAAQRQwvDIZgACCSAAAjuvkFffXPqaSa2NPTsE	8233548675	72357	1	2026-04-30 19:09:08.064812+08
205	-1003883297177	AgACAgUAAyEFAATndmmZAAIFqGnyHoxeIDb_LTqa9B6C7ueKl-zVAAI3D2sbO6-QV0tfg4Dl8vThAQADAgADeQADOwQ	8590155218	74168	1	2026-04-30 19:09:08.187561+08
206	-1003883297177	AgACAgUAAyEFAATndmmZAAIFrGnyISCBWPuNwqqTj0oXuFqCsBrhAAI-D2sbO6-QV9ZeFBLUmjxIAQADAgADeQADOwQ	7163866386	55516	1	2026-04-30 19:09:08.295164+08
207	-1003883297177	BQACAgUAAyEFAATndmmZAAIFo2nyHbrMnZDw4vIL-gZ6L8P00vJaAALdIAACa-uRV1vnvX9uLiHaOwQ	7510241572	31088	1	2026-04-30 19:09:08.402839+08
208	-1003883297177	BQACAgUAAyEFAATndmmZAAIFoWnyHZFMFrkOIM_oMXC4a515uPk_AAIFIAACO6-QV8jsSW6cvXcyOwQ	7625201169	56773	1	2026-04-30 19:09:08.505603+08
209	-1003883297177	BQACAgUAAyEFAATndmmZAAIFpmnyHiFYCSBsRoRGAtXtXrxezYWFAALJIAACyP2QV-NHxs3O8pkKOwQ	8178120332	59242	1	2026-04-30 19:09:08.607119+08
210	-1003883297177	BQACAgUAAyEFAATndmmZAAIFqWnyHsU6tddnnPM57qZaqLVZo3zkAAIOIAACO6-QV7ceCU7KUwtwOwQ	6562376911	17025	1	2026-04-30 19:09:08.713482+08
211	-1003883297177	AgACAgUAAyEFAATndmmZAAIFp2nyHiWvB3LidaGs2M2uKpzd88WzAAI2D2sbO6-QVyfRfs4tZaY5AQADAgADeQADOwQ	8532682955	74306	1	2026-04-30 19:09:09.074891+08
212	-1003883297177	AgACAgUAAyEFAATndmmZAAIFqmnyHx5ZhQtvne6JQ9_2RdGA9IeCAAI4D2sbO6-QV13cPeIdvDgcAQADAgADeQADOwQ	7736673658	29337	1	2026-04-30 19:09:09.295446+08
213	-1003883297177	AgACAgUAAyEFAATndmmZAAIFrWnyJMwT8zr9uX1rciX5182d0T35AAJCD2sbO6-QV9kUpY1UsmlNAQADAgADeQADOwQ	8763615403	74314	1	2026-04-30 19:09:09.405685+08
214	-1003883297177	AgACAgUAAyEFAATndmmZAAIFq2nyII8NmbAz5YC6xdYNhI3bRZAdAAI8D2sbO6-QV1oaVsdmWgZAAQADAgADeQADOwQ	8580988163	74114	1	2026-04-30 19:09:09.50753+08
215	-1003883297177	BQACAgUAAyEFAATndmmZAAIFtGny6ndKYx4bRtYF4i0HU3kW_CVBAAJgHwACO6-YV0aYDsXr3xofOwQ	7056750099	4257	1	2026-04-30 19:09:09.618577+08
216	-1003883297177	BQACAgUAAyEFAATndmmZAAIFtmny6shAEDUAAbjDPCzrNM1bjWZUpQACYh8AAjuvmFe03Y843Y_yzjsE	7625201169	56773	1	2026-04-30 19:09:09.83102+08
217	-1003883297177	BQACAgUAAyEFAATndmmZAAIFsmny6RWCzPJirU7P6u0Zcbu-WLnJAALaHQACa-uZVwLxag2-kl2gOwQ	7510241572	31088	1	2026-04-30 19:09:09.945207+08
218	-1003883297177	BQACAgUAAyEFAATndmmZAAIFsGny5wKTF799ivUd9vA2GjAr55NCAAJUHwACO6-YV9X1o3go7_SoOwQ	6562376911	17025	1	2026-04-30 19:09:10.053182+08
219	-1003883297177	AgACAgUAAyEFAATndmmZAAIFuWny67E4ROzt8R_ptpS2RajZ3Q84AAKBD2sbO6-YVzV92jZcWy9GAQADAgADeQADOwQ	8590155218	74168	1	2026-04-30 19:09:10.162096+08
220	-1003883297177	AgACAgUAAyEFAATndmmZAAIFtWny6o4JsJD7mrIEHYi70SoVwccLAAJ7D2sbO6-YVzHbrgyoD5-ZAQADAgADeQADOwQ	8642653065	74322	1	2026-04-30 19:09:10.369497+08
221	-1003883297177	AgACAgUAAyEFAATndmmZAAIFs2ny6kokltPRbYujxXW80xm9XBE4AAJ6D2sbO6-YV79Oxwv_1PsXAQADAgADeQADOwQ	8532682955	74306	1	2026-04-30 19:09:10.469877+08
222	-1003883297177	AgACAgUAAyEFAATndmmZAAIFuGny6tl6A98plzuqnXHUZSN12QNnAAJ-D2sbO6-YV8Ga4SixF0xNAQADAgADeQADOwQ	7736673658	29337	1	2026-04-30 19:09:10.571115+08
223	-1003883297177	BQACAgUAAyEFAATndmmZAAIFsWny6JovDdkvYuWGjc7GmECpjuCQAAJaHwACO6-YV_7VcvzV-L_7OwQ	8233548675	72357	1	2026-04-30 19:09:10.678101+08
224	-1003883297177	AgACAgUAAyEFAATndmmZAAIFt2ny6sl6_89qXGqRd19AtBYmLzt7AAJ9D2sbO6-YV20oi8a9V4FGAQADAgADeQADOwQ	7074207060	58073	1	2026-04-30 19:09:10.780859+08
225	-1003883297177	BQACAgUAAyEFAATndmmZAAIFvGny7ae5k1pzQ5vW5g68cZ3s99YwAAJqHwACO6-YVxJQgRITh3DmOwQ	7163866386	55516	1	2026-04-30 19:09:10.894387+08
226	-1003883297177	AgACAgUAAyEFAATndmmZAAIFv2ny7hXsLQABzZmCyGuZbMPLmXRqLAAChw9rGzuvmFctck8XUSB4OAEAAwIAA3kAAzsE	7625966687	56753	1	2026-04-30 19:09:10.995406+08
227	-1003883297177	BQACAgUAAyEFAATndmmZAAIFvmny7gkfmRv-z-UnXDIEG7ISFtw8AAIjHAACyP2YVyl_lIw3ldgvOwQ	8178120332	59242	1	2026-04-30 19:09:11.111534+08
228	-1003883297177	AgACAgUAAyEFAATndmmZAAIFu2ny7UnUyCMr7XOneIJr83bRJVyqAAKFD2sbO6-YV-v2d4OBC76mAQADAgADeQADOwQ	8580988163	74114	1	2026-04-30 19:09:11.220945+08
229	-1003883297177	BQACAgUAAyEFAATndmmZAAIFvWny7gjAqQkAAS1zkmCIvFP7P8r7sQACbB8AAjuvmFd7cSWbKLXyljsE	6886314602	16908	1	2026-04-30 19:09:11.440711+08
\.


--
-- TOC entry 5294 (class 0 OID 17885)
-- Dependencies: 234
-- Data for Name: effective_leave_days; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.effective_leave_days (id, employee_id, leave_date, shift_id, leave_reason, application_remark, application_id) FROM stdin;
\.


--
-- TOC entry 5296 (class 0 OID 17895)
-- Dependencies: 236
-- Data for Name: effective_temporary_leaves; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.effective_temporary_leaves (id, employee_id, effective_date, shift_id, reason_remark, leave_start_at, leave_end_at, application_id) FROM stdin;
1	7122	2026-04-11 00:00:00+08	0	嘿嘿	2026-04-11 22:25:00+08	2026-04-11 22:30:00+08	8
2	7122	2026-04-12 00:00:00+08	0	出门吃饭	2026-04-12 22:40:00+08	2026-04-12 22:50:00+08	9
\.


--
-- TOC entry 5306 (class 0 OID 17941)
-- Dependencies: 246
-- Data for Name: event_logs; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.event_logs (id, event_name, related_event_name, result, related_event_id, created_at, processed_at, retry_count, error_message) FROM stdin;
1	NOTIFICATION_TRIGGERED	approval_task_queue	CREATED	5	2026-04-10 18:07:27.647347+08	\N	0	\N
2	NOTIFICATION_TRIGGERED	leave_approval_result	CREATED	5	2026-04-10 18:07:42.34931+08	\N	0	\N
3	AUDIT_TASK_TRIGGERED	audit_task_init_checkin	CREATED	120260410	2026-04-10 20:22:34.114796+08	\N	0	\N
4	AUDIT_TASK_TRIGGERED	audit_task_init_checkout	CREATED	120260410	2026-04-10 20:22:34.198569+08	\N	0	\N
5	NOTIFICATION_TRIGGERED	audit_notice	CREATED	120260410	2026-04-10 20:22:34.385572+08	\N	0	\N
6	NOTIFICATION_TRIGGERED	audit_notice	CREATED	120260410	2026-04-10 20:22:34.385572+08	\N	0	\N
7	NOTIFICATION_TRIGGERED	audit_notice	CREATED	20260410	2026-04-10 20:32:58.092071+08	\N	0	\N
8	NOTIFICATION_TRIGGERED	audit_notice	CREATED	20260410	2026-04-10 20:32:58.092071+08	\N	0	\N
9	NOTIFICATION_TRIGGERED	audit_notice	CREATED	120260410	2026-04-10 20:32:59.203536+08	\N	0	\N
10	NOTIFICATION_TRIGGERED	audit_notice	CREATED	20260410	2026-04-10 20:48:21.357271+08	\N	0	\N
11	NOTIFICATION_TRIGGERED	audit_notice	CREATED	120260410	2026-04-10 20:48:21.979734+08	\N	0	\N
12	AUDIT_TASK_TRIGGERED	audit_task_init_checkin	CREATED	20260409	2026-04-10 21:16:49.500067+08	\N	0	\N
13	AUDIT_TASK_TRIGGERED	audit_task_init_checkout	CREATED	20260409	2026-04-10 21:16:49.58959+08	\N	0	\N
14	NOTIFICATION_TRIGGERED	audit_notice	CREATED	20260409	2026-04-10 21:16:49.778181+08	\N	0	\N
15	NOTIFICATION_TRIGGERED	audit_notice	CREATED	20260409	2026-04-10 21:16:49.778181+08	\N	0	\N
16	NOTIFICATION_TRIGGERED	audit_notice	CREATED	20260409	2026-04-10 21:16:49.778181+08	\N	0	\N
17	NOTIFICATION_TRIGGERED	audit_notice	CREATED	20260409	2026-04-10 21:21:38.208512+08	\N	0	\N
18	NOTIFICATION_TRIGGERED	audit_notice	CREATED	20260409	2026-04-10 21:21:38.208512+08	\N	0	\N
19	NOTIFICATION_TRIGGERED	audit_notice	CREATED	20260409	2026-04-10 21:21:38.208512+08	\N	0	\N
20	NOTIFICATION_TRIGGERED	audit_notice	CREATED	120260410	2026-04-10 21:21:39.225087+08	\N	0	\N
21	NOTIFICATION_TRIGGERED	audit_notice	CREATED	120260410	2026-04-10 21:21:39.225087+08	\N	0	\N
22	NOTIFICATION_TRIGGERED	audit_notice	CREATED	20260410	2026-04-10 21:26:48.825371+08	\N	0	\N
23	NOTIFICATION_TRIGGERED	audit_notice	CREATED	20260410	2026-04-10 21:26:48.825371+08	\N	0	\N
24	NOTIFICATION_TRIGGERED	audit_notice	CREATED	20260409	2026-04-10 21:56:31.150591+08	\N	0	\N
25	NOTIFICATION_TRIGGERED	audit_notice	CREATED	20260409	2026-04-10 21:56:31.150591+08	\N	0	\N
26	NOTIFICATION_TRIGGERED	audit_notice	CREATED	20260409	2026-04-10 21:56:31.150591+08	\N	0	\N
27	NOTIFICATION_TRIGGERED	audit_notice	CREATED	120260410	2026-04-10 21:56:32.803197+08	\N	0	\N
28	NOTIFICATION_TRIGGERED	audit_notice	CREATED	120260410	2026-04-10 21:56:32.803197+08	\N	0	\N
29	NOTIFICATION_TRIGGERED	audit_notice	CREATED	20260409	2026-04-10 22:02:09.342919+08	\N	0	\N
30	NOTIFICATION_TRIGGERED	audit_notice	CREATED	20260409	2026-04-10 22:02:09.342919+08	\N	0	\N
31	NOTIFICATION_TRIGGERED	audit_notice	CREATED	20260409	2026-04-10 22:02:09.342919+08	\N	0	\N
32	NOTIFICATION_TRIGGERED	audit_notice	CREATED	120260410	2026-04-10 22:02:10.953993+08	\N	0	\N
33	NOTIFICATION_TRIGGERED	audit_notice	CREATED	120260410	2026-04-10 22:02:10.953993+08	\N	0	\N
34	NOTIFICATION_TRIGGERED	audit_notice	CREATED	20260410	2026-04-10 22:07:22.179538+08	\N	0	\N
35	NOTIFICATION_TRIGGERED	audit_notice	CREATED	20260410	2026-04-10 22:07:22.179538+08	\N	0	\N
36	NOTIFICATION_TRIGGERED	audit_notice	CREATED	20260410	2026-04-10 22:15:54.47126+08	\N	0	\N
37	NOTIFICATION_TRIGGERED	audit_notice	CREATED	20260410	2026-04-10 22:15:54.47126+08	\N	0	\N
38	NOTIFICATION_TRIGGERED	audit_notice	CREATED	120260410	2026-04-10 22:15:55.836496+08	\N	0	\N
39	NOTIFICATION_TRIGGERED	audit_notice	CREATED	120260410	2026-04-10 22:15:55.836496+08	\N	0	\N
40	NOTIFICATION_TRIGGERED	audit_notice	CREATED	120260410	2026-04-10 22:21:05.40088+08	\N	0	\N
41	NOTIFICATION_TRIGGERED	audit_notice	CREATED	120260410	2026-04-10 22:21:05.40088+08	\N	0	\N
42	NOTIFICATION_TRIGGERED	audit_notice	CREATED	20260410	2026-04-10 22:26:15.818472+08	\N	0	\N
43	NOTIFICATION_TRIGGERED	audit_notice	CREATED	20260410	2026-04-10 22:26:15.818472+08	\N	0	\N
44	NOTIFICATION_TRIGGERED	audit_notice	CREATED	120260410	2026-04-10 22:47:13.78486+08	\N	0	\N
45	NOTIFICATION_TRIGGERED	audit_notice	CREATED	120260410	2026-04-10 22:47:13.78486+08	\N	0	\N
46	NOTIFICATION_TRIGGERED	audit_notice	CREATED	120260410	2026-04-10 22:47:13.78486+08	\N	0	\N
47	NOTIFICATION_TRIGGERED	audit_notice	CREATED	120260410	2026-04-10 22:47:13.78486+08	\N	0	\N
48	NOTIFICATION_TRIGGERED	audit_notice	CREATED	20260410	2026-04-10 22:52:26.117322+08	\N	0	\N
49	NOTIFICATION_TRIGGERED	audit_notice	CREATED	20260410	2026-04-10 22:52:26.117322+08	\N	0	\N
50	NOTIFICATION_TRIGGERED	audit_notice	CREATED	20260410	2026-04-10 22:52:26.117322+08	\N	0	\N
51	NOTIFICATION_TRIGGERED	audit_notice	CREATED	20260410	2026-04-10 23:02:40.828661+08	\N	0	\N
52	NOTIFICATION_TRIGGERED	audit_notice	CREATED	120260410	2026-04-10 23:02:41.727003+08	\N	0	\N
53	NOTIFICATION_TRIGGERED	audit_notice	CREATED	120260410	2026-04-10 23:16:21.992188+08	\N	0	\N
54	NOTIFICATION_TRIGGERED	audit_notice	CREATED	20260410	2026-04-10 23:20:13.914717+08	\N	0	\N
55	NOTIFICATION_TRIGGERED	audit_notice	CREATED	20260410	2026-04-10 23:20:13.914717+08	\N	0	\N
56	NOTIFICATION_TRIGGERED	audit_notice	CREATED	120260410	2026-04-10 23:20:15.187291+08	\N	0	\N
57	NOTIFICATION_TRIGGERED	audit_notice	CREATED	120260410	2026-04-10 23:34:19.512684+08	\N	0	\N
58	NOTIFICATION_TRIGGERED	audit_notice	CREATED	120260410	2026-04-10 23:34:19.512684+08	\N	0	\N
59	NOTIFICATION_TRIGGERED	audit_notice	CREATED	20260410	2026-04-11 00:09:15.481429+08	\N	0	\N
60	AUDIT_TASK_TRIGGERED	audit_task_init_checkin	CREATED	120260411	2026-04-11 11:01:59.799246+08	\N	0	\N
61	AUDIT_TASK_TRIGGERED	audit_task_init_checkin	CREATED	20260411	2026-04-11 13:45:36.4344+08	\N	0	\N
62	APPROVAL_NOTIFICATION_TRIGGERED	approval_task	CREATED	6	2026-04-11 13:46:36.407737+08	\N	0	\N
63	NOTIFICATION_TRIGGERED	audit_notice	CREATED	20260411	2026-04-11 13:50:39.593281+08	\N	0	\N
64	NOTIFICATION_TRIGGERED	audit_notice	CREATED	20260411	2026-04-11 13:50:39.593281+08	\N	0	\N
65	NOTIFICATION_TRIGGERED	audit_notice	CREATED	20260411	2026-04-11 13:50:39.593281+08	\N	0	\N
66	NOTIFICATION_TRIGGERED	audit_notice	CREATED	120260411	2026-04-11 14:00:45.622155+08	\N	0	\N
67	NOTIFICATION_TRIGGERED	audit_notice	CREATED	120260411	2026-04-11 14:00:45.622155+08	\N	0	\N
68	NOTIFICATION_TRIGGERED	audit_notice	CREATED	120260411	2026-04-11 14:00:45.622155+08	\N	0	\N
69	NOTIFICATION_TRIGGERED	audit_notice	CREATED	120260411	2026-04-11 14:00:45.622155+08	\N	0	\N
70	APPROVAL_NOTIFICATION_TRIGGERED	approval_task	CREATED	7	2026-04-11 15:05:45.869075+08	\N	0	\N
71	NOTIFICATION_TRIGGERED	approval_task	CREATED	7	2026-04-11 15:05:51.709042+08	\N	0	\N
72	NOTIFICATION_TRIGGERED	approval_task	CREATED	7	2026-04-11 15:05:51.709042+08	\N	0	\N
73	APPROVAL_NOTIFICATION_TRIGGERED	approval_task	CREATED	8	2026-04-11 16:27:12.655951+08	\N	0	\N
74	NOTIFICATION_TRIGGERED	approval_task	CREATED	8	2026-04-11 16:27:18.137521+08	\N	0	\N
75	NOTIFICATION_TRIGGERED	approval_task	CREATED	8	2026-04-11 16:27:18.137521+08	\N	0	\N
76	APPROVAL_NOTIFICATION_TRIGGERED	approval_task	CREATED	9	2026-04-11 16:32:39.660374+08	\N	0	\N
77	NOTIFICATION_TRIGGERED	approval_task	CREATED	9	2026-04-11 16:32:45.026213+08	\N	0	\N
78	NOTIFICATION_TRIGGERED	approval_task	CREATED	9	2026-04-11 16:32:45.026213+08	\N	0	\N
79	APPROVAL_NOTIFICATION_TRIGGERED	approval_task	CREATED	10	2026-04-11 16:41:07.918458+08	\N	0	\N
80	NOTIFICATION_TRIGGERED	approval_task	CREATED	10	2026-04-11 16:41:12.256881+08	\N	0	\N
81	NOTIFICATION_TRIGGERED	approval_task	CREATED	10	2026-04-11 16:41:12.256881+08	\N	0	\N
82	APPROVAL_NOTIFICATION_TRIGGERED	approval_task	CREATED	11	2026-04-11 19:56:43.311124+08	\N	0	\N
83	APPROVAL_NOTIFICATION_TRIGGERED	approval_task	CREATED	12	2026-04-11 19:59:26.844536+08	\N	0	\N
84	NOTIFICATION_TRIGGERED	approval_task	CREATED	12	2026-04-11 19:59:33.939853+08	\N	0	\N
85	NOTIFICATION_TRIGGERED	approval_task	CREATED	12	2026-04-11 19:59:33.939853+08	\N	0	\N
86	AUDIT_TASK_TRIGGERED	audit_task_init_checkout	CREATED	20260411	2026-04-11 20:02:37.525381+08	\N	0	\N
87	NOTIFICATION_TRIGGERED	audit_notice	CREATED	20260411	2026-04-11 20:02:37.615949+08	\N	0	\N
88	NOTIFICATION_TRIGGERED	audit_notice	CREATED	20260411	2026-04-11 20:02:37.615949+08	\N	0	\N
89	NOTIFICATION_TRIGGERED	audit_notice	CREATED	20260411	2026-04-11 20:02:37.615949+08	\N	0	\N
90	AUDIT_TASK_TRIGGERED	audit_task_init_checkout	CREATED	120260411	2026-04-11 20:02:39.385109+08	\N	0	\N
91	NOTIFICATION_TRIGGERED	audit_notice	CREATED	120260411	2026-04-11 20:02:39.467975+08	\N	0	\N
92	NOTIFICATION_TRIGGERED	audit_notice	CREATED	120260411	2026-04-11 20:02:39.467975+08	\N	0	\N
93	NOTIFICATION_TRIGGERED	audit_notice	CREATED	120260411	2026-04-11 20:02:39.467975+08	\N	0	\N
94	APPROVAL_NOTIFICATION_TRIGGERED	approval_task	CREATED	13	2026-04-11 22:25:30.148395+08	\N	0	\N
95	NOTIFICATION_TRIGGERED	approval_task	CREATED	13	2026-04-11 22:25:35.283795+08	\N	0	\N
96	NOTIFICATION_TRIGGERED	approval_task	CREATED	13	2026-04-11 22:25:35.283795+08	\N	0	\N
97	NOTIFICATION_TRIGGERED	audit_notice	CREATED	20260411	2026-04-11 23:00:03.104175+08	\N	0	\N
98	NOTIFICATION_TRIGGERED	audit_notice	CREATED	120260411	2026-04-11 23:00:04.286255+08	\N	0	\N
99	AUDIT_TASK_TRIGGERED	audit_task_init_checkin	CREATED	20260412	2026-04-12 01:58:39.747764+08	\N	0	\N
100	NOTIFICATION_TRIGGERED	audit_notice	CREATED	20260412	2026-04-12 02:02:56.791732+08	\N	0	\N
101	NOTIFICATION_TRIGGERED	audit_notice	CREATED	20260412	2026-04-12 02:02:56.791732+08	\N	0	\N
102	NOTIFICATION_TRIGGERED	audit_notice	CREATED	20260412	2026-04-12 02:02:56.791732+08	\N	0	\N
103	QC_ROUND_OPENED	qc_round	CREATED	20260412	2026-04-12 02:15:04.655624+08	\N	0	\N
104	QC_ROUND_OPENED	qc_round	CREATED	20260412	2026-04-12 02:20:10.58798+08	\N	0	\N
112	QC_ROUND_OPENED	qc_round	CREATED	20260412	2026-04-12 12:40:01.372093+08	2026-04-12 12:55:11.695932+08	0	\N
113	NOTIFICATION_TRIGGERED	audit_notice	CREATED	20260412	2026-04-12 13:03:24.288649+08	\N	0	\N
114	NOTIFICATION_TRIGGERED	qc_shift_summary	CREATED	20260412	2026-04-12 13:10:00.558696+08	\N	0	\N
115	NOTIFICATION_TRIGGERED	audit_notice	CREATED	120260412	2026-04-12 14:01:52.830326+08	\N	0	\N
116	NOTIFICATION_TRIGGERED	audit_notice	CREATED	120260412	2026-04-12 14:01:52.830326+08	\N	0	\N
117	NOTIFICATION_TRIGGERED	audit_notice	CREATED	120260412	2026-04-12 14:01:52.830326+08	\N	0	\N
120	QC_ROUND_OPENED	qc_round	CREATED	120260412	2026-04-12 18:33:34.269846+08	2026-04-12 18:51:43.273735+08	0	\N
121	AUDIT_TASK_TRIGGERED	audit_task_init_checkout	CREATED	120260412	2026-04-12 20:01:49.863666+08	\N	0	\N
105	QC_ROUND_OPENED	qc_round	CREATED	20260412	2026-04-12 02:36:40.704931+08	2026-04-12 11:03:29.222908+08	0	\N
109	AUDIT_TASK_TRIGGERED	audit_task_init_checkout	CREATED	20260412	2026-04-12 10:04:13.297655+08	\N	0	\N
122	QC_ROUND_OPENED	qc_round	CREATED	120260412	2026-04-12 20:30:06.376007+08	2026-04-12 20:40:50.078273+08	0	\N
106	QC_ROUND_OPENED	qc_round	CREATED	20260412	2026-04-12 04:40:09.136736+08	2026-04-12 11:03:29.700789+08	0	\N
107	QC_ROUND_OPENED	qc_round	CREATED	20260412	2026-04-12 06:40:00.92831+08	2026-04-12 11:03:30.160651+08	0	\N
123	NOTIFICATION_TRIGGERED	approval_task_queue	CREATED	14	2026-04-12 21:56:57.23834+08	\N	0	\N
108	QC_ROUND_OPENED	qc_round	CREATED	20260412	2026-04-12 08:40:09.610963+08	2026-04-12 11:03:30.624303+08	0	\N
124	NOTIFICATION_TRIGGERED	leave_approval_result	CREATED	6	2026-04-12 21:58:01.034407+08	\N	0	\N
110	QC_ROUND_OPENED	qc_round	CREATED	20260412	2026-04-12 10:40:09.821096+08	2026-04-12 11:03:31.090097+08	0	\N
111	AUDIT_TASK_TRIGGERED	audit_task_init_checkin	CREATED	120260412	2026-04-12 11:04:31.884673+08	\N	0	\N
126	APPROVAL_NOTIFICATION_TRIGGERED	approval_task	CREATED	15	2026-04-12 22:40:34.447706+08	\N	0	\N
127	NOTIFICATION_TRIGGERED	approval_task	CREATED	15	2026-04-12 22:41:25.891267+08	\N	0	\N
128	NOTIFICATION_TRIGGERED	approval_task	CREATED	15	2026-04-12 22:41:25.891267+08	\N	0	\N
129	NOTIFICATION_TRIGGERED	audit_notice	CREATED	120260412	2026-04-12 23:00:08.720505+08	\N	0	\N
130	NOTIFICATION_TRIGGERED	qc_shift_summary	CREATED	120260412	2026-04-12 23:10:09.170464+08	\N	0	\N
131	AUDIT_TASK_TRIGGERED	audit_task_init_checkin	CREATED	20260413	2026-04-13 11:04:03.526078+08	\N	0	\N
132	AUDIT_TASK_TRIGGERED	audit_task_init_checkin	CREATED	120260413	2026-04-13 11:04:03.661526+08	\N	0	\N
133	NOTIFICATION_TRIGGERED	audit_notice	CREATED	20260413	2026-04-13 14:02:02.330198+08	\N	0	\N
134	NOTIFICATION_TRIGGERED	audit_notice	CREATED	20260413	2026-04-13 14:02:02.330198+08	\N	0	\N
135	NOTIFICATION_TRIGGERED	audit_notice	CREATED	20260413	2026-04-13 14:02:02.330198+08	\N	0	\N
136	NOTIFICATION_TRIGGERED	audit_notice	CREATED	120260413	2026-04-13 14:02:03.968069+08	\N	0	\N
137	NOTIFICATION_TRIGGERED	audit_notice	CREATED	120260413	2026-04-13 14:02:03.968069+08	\N	0	\N
138	NOTIFICATION_TRIGGERED	audit_notice	CREATED	120260413	2026-04-13 14:02:03.968069+08	\N	0	\N
119	QC_ROUND_OPENED	qc_round	CREATED	120260412	2026-04-12 16:30:05.715106+08	2026-04-13 16:25:46.442245+08	0	\N
125	QC_ROUND_OPENED	qc_round	CREATED	120260412	2026-04-12 22:30:02.215643+08	2026-04-13 16:25:46.961851+08	0	\N
118	QC_ROUND_OPENED	qc_round	CREATED	120260412	2026-04-12 14:30:05.357254+08	2026-04-13 14:52:27.191829+08	0	\N
139	QC_ROUND_OPENED	qc_round	CREATED	120260413	2026-04-13 14:30:02.723142+08	2026-04-13 14:53:08.069734+08	0	\N
140	QC_ROUND_OPENED	qc_round	CREATED	120260413	2026-04-13 16:30:03.688715+08	2026-04-13 16:45:15.516992+08	0	\N
141	QC_ROUND_OPENED	qc_round	CREATED	120260413	2026-04-13 18:30:04.57284+08	2026-04-13 18:35:59.02917+08	0	\N
142	AUDIT_TASK_TRIGGERED	audit_task_init_checkout	CREATED	20260413	2026-04-13 20:02:47.309731+08	\N	0	\N
143	AUDIT_TASK_TRIGGERED	audit_task_init_checkout	CREATED	120260413	2026-04-13 20:02:48.20828+08	\N	0	\N
144	QC_ROUND_OPENED	qc_round	CREATED	120260413	2026-04-13 20:30:05.986289+08	2026-04-13 20:45:17.823319+08	0	\N
145	QC_ROUND_OPENED	qc_round	CREATED	120260413	2026-04-13 22:30:04.36208+08	2026-04-13 22:45:20.149731+08	0	\N
146	NOTIFICATION_TRIGGERED	audit_notice	CREATED	20260413	2026-04-13 23:03:30.638067+08	\N	0	\N
147	NOTIFICATION_TRIGGERED	audit_notice	CREATED	120260413	2026-04-13 23:03:31.754797+08	\N	0	\N
148	NOTIFICATION_TRIGGERED	qc_shift_summary	CREATED	120260413	2026-04-13 23:10:06.831679+08	\N	0	\N
149	AUDIT_TASK_TRIGGERED	audit_task_init_checkin	CREATED	20260414	2026-04-14 11:04:54.656402+08	\N	0	\N
150	AUDIT_TASK_TRIGGERED	audit_task_init_checkin	CREATED	120260414	2026-04-14 11:04:54.791184+08	\N	0	\N
151	NOTIFICATION_TRIGGERED	audit_notice	CREATED	20260414	2026-04-14 14:03:05.115597+08	\N	0	\N
152	NOTIFICATION_TRIGGERED	audit_notice	CREATED	20260414	2026-04-14 14:03:05.115597+08	\N	0	\N
153	NOTIFICATION_TRIGGERED	audit_notice	CREATED	20260414	2026-04-14 14:03:05.115597+08	\N	0	\N
154	NOTIFICATION_TRIGGERED	audit_notice	CREATED	120260414	2026-04-14 14:03:06.96786+08	\N	0	\N
155	NOTIFICATION_TRIGGERED	audit_notice	CREATED	120260414	2026-04-14 14:03:06.96786+08	\N	0	\N
156	NOTIFICATION_TRIGGERED	audit_notice	CREATED	120260414	2026-04-14 14:03:06.96786+08	\N	0	\N
157	AUDIT_TASK_TRIGGERED	audit_task_init_checkout	CREATED	20260414	2026-04-14 20:03:31.52835+08	\N	0	\N
158	AUDIT_TASK_TRIGGERED	audit_task_init_checkout	CREATED	120260414	2026-04-14 20:03:32.126795+08	\N	0	\N
159	NOTIFICATION_TRIGGERED	audit_notice	CREATED	20260414	2026-04-14 23:03:52.351398+08	\N	0	\N
160	NOTIFICATION_TRIGGERED	audit_notice	CREATED	120260414	2026-04-14 23:03:53.074021+08	\N	0	\N
161	AUDIT_TASK_TRIGGERED	audit_task_init_checkin	CREATED	20260419	2026-04-19 14:32:27.205164+08	\N	0	\N
162	NOTIFICATION_TRIGGERED	audit_notice	CREATED	20260419	2026-04-19 14:32:27.338861+08	\N	0	\N
163	NOTIFICATION_TRIGGERED	audit_notice	CREATED	20260419	2026-04-19 14:32:27.338861+08	\N	0	\N
164	NOTIFICATION_TRIGGERED	audit_notice	CREATED	20260419	2026-04-19 14:32:27.338861+08	\N	0	\N
165	AUDIT_TASK_TRIGGERED	audit_task_init_checkin	CREATED	120260419	2026-04-19 14:32:29.425785+08	\N	0	\N
166	NOTIFICATION_TRIGGERED	audit_notice	CREATED	120260419	2026-04-19 14:32:29.577716+08	\N	0	\N
167	NOTIFICATION_TRIGGERED	audit_notice	CREATED	120260419	2026-04-19 14:32:29.577716+08	\N	0	\N
168	NOTIFICATION_TRIGGERED	audit_notice	CREATED	120260419	2026-04-19 14:32:29.577716+08	\N	0	\N
169	AUDIT_TASK_TRIGGERED	audit_task_init_checkout	CREATED	20260419	2026-04-19 20:03:05.610862+08	\N	0	\N
170	AUDIT_TASK_TRIGGERED	audit_task_init_checkout	CREATED	120260419	2026-04-19 20:03:06.116069+08	\N	0	\N
171	NOTIFICATION_TRIGGERED	audit_notice	CREATED	20260419	2026-04-19 23:03:15.246391+08	\N	0	\N
172	NOTIFICATION_TRIGGERED	audit_notice	CREATED	120260419	2026-04-19 23:03:16.500597+08	\N	0	\N
173	AUDIT_TASK_TRIGGERED	audit_task_init_checkin	CREATED	20260430	2026-04-30 19:08:47.282972+08	\N	0	\N
174	NOTIFICATION_TRIGGERED	audit_notice	CREATED	20260430	2026-04-30 19:08:47.392287+08	\N	0	\N
175	NOTIFICATION_TRIGGERED	audit_notice	CREATED	20260430	2026-04-30 19:08:47.392287+08	\N	0	\N
176	NOTIFICATION_TRIGGERED	audit_notice	CREATED	20260430	2026-04-30 19:08:47.392287+08	\N	0	\N
177	AUDIT_TASK_TRIGGERED	audit_task_init_checkin	CREATED	120260430	2026-04-30 19:08:48.97153+08	\N	0	\N
178	NOTIFICATION_TRIGGERED	audit_notice	CREATED	120260430	2026-04-30 19:08:49.079729+08	\N	0	\N
179	NOTIFICATION_TRIGGERED	audit_notice	CREATED	120260430	2026-04-30 19:08:49.079729+08	\N	0	\N
180	NOTIFICATION_TRIGGERED	audit_notice	CREATED	120260430	2026-04-30 19:08:49.079729+08	\N	0	\N
181	AUDIT_TASK_TRIGGERED	audit_task_init_checkout	CREATED	20260430	2026-04-30 20:00:07.293453+08	\N	0	\N
182	AUDIT_TASK_TRIGGERED	audit_task_init_checkout	CREATED	120260430	2026-04-30 20:00:07.851541+08	\N	0	\N
\.


--
-- TOC entry 5288 (class 0 OID 17855)
-- Dependencies: 228
-- Data for Name: leave_applications; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.leave_applications (id, employee_id, organization_id, shift_id, start_at, end_at, leave_reason, remark, status, completed_at, created_at) FROM stdin;
5	7122	0	0	2026-04-15 01:00:00+08	2026-04-17 00:59:59+08	年假		APPROVED	2026-04-10 18:07:42.34931+08	2026-04-10 18:07:26.975953+08
6	7122	0	0	2026-12-12 01:00:00+08	2026-12-16 00:59:59+08	年假		REJECTED	2026-04-12 21:58:01.034407+08	2026-04-12 21:56:56.572054+08
\.


--
-- TOC entry 5314 (class 0 OID 17984)
-- Dependencies: 254
-- Data for Name: notification_queue; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.notification_queue (id, log_id, notify_tg_id, template_id, reply_content, attachment_id, delivery_result, created_at, processed_at, retry_count, error_message, task_status) FROM stdin;
81	84	6332760420	1002	您的离岗申请：\n"\n日期：2026-04-11\n离岗时间：19:00-20:00\n离岗原因：嫖娼\n"\n审批结果为：通过\n审批理由：无	\N	SENT	2026-04-11 19:59:33.939853+08	2026-04-11 19:59:34.210746+08	0	\N	DONE
110	118	-1003883297177	2004	质检开启公告\n\n部门：UXSJ\n班次：13:00 — 22:00\n时区：Asia/Bangkok\n\n今日第1轮抽检已经开始，请以下成员留意本机器人私信并在15分钟内完成质检任务，质检结果将写入数据库。\n\nKarina\nbrick\nBrucewillis\n\nps：如果您未收到质检任务请私信机器人并发送指令 /qc ，可重启质检流程。	\N	UNDELIVERABLE	2026-04-12 14:30:05.357254+08	2026-04-12 14:30:05.529461+08	0	Telegram server says - Bad Request: chat not found	DONE
84	88	6332760420	3004	您负责的Asia/Bangkok 12:50 —— 22:00 的班次目前已经开始，应到岗3人，已到岗0人。\n\n以下成员应到岗但仍未打卡，请确认员工状态：\n<a href="https://t.me/jeffery1836">test</a>\n<a href="https://t.me/Y_TC_NOHHAEIL">NOHHAEIL</a>\n<a href="https://t.me/Sanverygoodli117">Sanchali</a>	\N	SENT	2026-04-11 20:02:37.615949+08	2026-04-11 20:02:52.837548+08	0	\N	DONE
112	120	-1003883297177	2004	质检开启公告\n\n部门：UXSJ\n班次：13:00 — 22:00\n时区：Asia/Bangkok\n\n今日第3轮抽检已经开始，请以下成员留意本机器人私信并在15分钟内完成质检任务，质检结果将写入数据库。\n\nKairice\nNlgelito\nSingjang\n\nps：如果您未收到质检任务请私信机器人并发送指令 /qc ，可重启质检流程。	\N	UNDELIVERABLE	2026-04-12 18:33:34.269846+08	2026-04-12 18:33:35.203363+08	0	Telegram server says - Bad Request: chat not found	DONE
87	92	7625966687	3004	您负责的Asia/Bangkok 13:00 —— 22:00 的班次目前已经开始，应到岗18人，已到岗15人。\n\n以下成员应到岗但仍未打卡，请确认员工状态：\n<a href="https://t.me/Y_UX_Brick">brick</a>\n<a href="https://t.me/Y_UX_Aikantui">aikantui</a>\n<a href="https://t.me/Y_UX_Nlgelito">Nlgelito</a>	\N	UNDELIVERABLE	2026-04-11 20:02:39.467975+08	2026-04-11 20:02:54.868438+08	0	Telegram server says - Bad Request: chat not found	DONE
90	95	6332760420	1002	您的离岗申请：\n"\n日期：2026-04-11\n离岗时间：21:25-21:30\n离岗原因：嘿嘿\n"\n审批结果为：通过\n审批理由：无	\N	SENT	2026-04-11 22:25:35.283795+08	2026-04-11 22:25:35.821958+08	0	\N	DONE
115	124	6332760420	1002	您的休假申请——\n\n英文名：test\n工号：7122\n部门：UXSJ\n休假类型：年假\n休假日期：2026-12-12 至 2026-12-15\n休假时长：4天\n申请备注：（无）\n\n审批结果为：驳回\n理由为：工作任务紧张缺乏人手，该假期不予批准\n审批人：<a href="https://t.me/jeffery1836">test</a>\n审批时间：2026-04-12 20:58:01	\N	SENT	2026-04-12 21:58:01.034407+08	2026-04-12 21:58:02.944328+08	0	\N	DONE
93	98	-1003883297177	3006	下班提醒：\n\n日期：2026-04-11\n部门：UXSJ\n班次：13:00 - 22:00\n时区：Asia/Bangkok\n\n本日工作时间已经结束，请各位同事不要忘记打卡，祝您生活愉快。	\N	UNDELIVERABLE	2026-04-11 23:00:04.286255+08	2026-04-11 23:00:07.634959+08	0	Telegram server says - Bad Request: chat not found	DONE
118	127	6332760420	1002	您的离岗申请：\n"\n日期：2026-04-12\n离岗时间：21:40-21:50\n离岗原因：出门吃饭\n"\n审批结果为：通过\n审批理由：无	\N	SENT	2026-04-12 22:41:25.891267+08	2026-04-12 22:41:26.589629+08	0	\N	DONE
96	102	6332760420	3005	<a href="https://t.me/jeffery1836">test</a>领导您好，\n\n部门：UXSJ\n班次：01:00 — 22:00\n时区：Asia/Bangkok\n\n<a href="https://t.me/jeffery1836">test</a>组：应到岗3人，实际到岗0人，0人报备休假，3人未打卡	\N	SENT	2026-04-12 02:02:56.791732+08	2026-04-12 02:03:03.371388+08	0	\N	DONE
99	105	-1003767543777	2004	<b>质检开启公告</b>\n本考勤群所绑定的班次已开启新一轮质检抽查。\n· 班次：<code>0</code>\n· 轮次：第 <b>1</b> 轮\n· 时区：<code>Asia/Bangkok</code>\n\n请被抽中的同事留意 Telegram 私信中的质检通知与示例材料，并按提示完成确认与提交。	\N	SENT	2026-04-12 02:36:40.704931+08	2026-04-12 02:36:41.357812+08	0	\N	DONE
121	130	-1003883297177	2005	<b>质检班次汇总公告</b>\n日期：2026-04-12\n部门：UXSJ\n班次：13:00 — 22:00\n时区：Asia/Bangkok\n\n今日共质检5轮，质检覆盖人员及结果公示如下：\n\nbrick：\n第1轮 无结果快照\n第2轮 无结果快照\n第3轮 无结果快照\n第4轮 无结果快照\n第5轮 无结果快照\n\nBrucewillis：\n第1轮 完成\n第2轮 无结果快照\n第3轮 无结果快照\n第4轮 无结果快照\n第5轮 无结果快照\n\nRapunzelli：\n第1轮 无结果快照\n第2轮 无结果快照\n第3轮 无结果快照\n第4轮 无结果快照\n第5轮 无结果快照\n\naikantui：\n第1轮 无结果快照\n第2轮 完成\n第3轮 无结果快照\n第4轮 无结果快照\n第5轮 无结果快照\n\nKarina：\n第1轮 无结果快照\n第2轮 无结果快照\n第3轮 无结果快照\n第4轮 无结果快照\n第5轮 无结果快照\n\ntanzaniju：\n第1轮 无结果快照\n第2轮 未完成\n第3轮 无结果快照\n第4轮 无结果快照\n第5轮 无结果快照\n\nKairice：\n第1轮 无结果快照\n第2轮 无结果快照\n第3轮 未完成\n第4轮 无结果快照\n第5轮 无结果快照\n\nNlgelito：\n第1轮 无结果快照\n第2轮 无结果快照\n第3轮 完成\n第4轮 无结果快照\n第5轮 无结果快照\n\nSingjang：\n第1轮 无结果快照\n第2轮 无结果快照\n第3轮 完成\n第4轮 无结果快照\n第5轮 无结果快照\n\nPadadgu：\n第1轮 无结果快照\n第2轮 无结果快照\n第3轮 无结果快照\n第4轮 完成\n第5轮 无结果快照\n\nXitanua：\n第1轮 无结果快照\n第2轮 无结果快照\n第3轮 无结果快照\n第4轮 完成\n第5轮 无结果快照\n\nGRENADA：\n第1轮 无结果快照\n第2轮 无结果快照\n第3轮 无结果快照\n第4轮 完成\n第5轮 无结果快照\n\nFoxieya：\n第1轮 无结果快照\n第2轮 无结果快照\n第3轮 无结果快照\n第4轮 无结果快照\n第5轮 完成\n\nBekahs：\n第1轮 无结果快照\n第2轮 无结果快照\n第3轮 无结果快照\n第4轮 无结果快照\n第5轮 无结果快照\n\nNAYXUA：\n第1轮 无结果快照\n第2轮 无结果快照\n第3轮 无结果快照\n第4轮 无结果快照\n第5轮 无结果快照\n\n质检结果已经录入，如有问题请及时联系管理员。\n	\N	SENT	2026-04-12 23:10:09.170464+08	2026-04-12 23:10:10.098895+08	0	\N	DONE
102	108	-1003767543777	2004	<b>质检开启公告</b>\n本考勤群所绑定的班次已开启新一轮质检抽查。\n· 班次：<code>0</code>\n· 轮次：第 <b>4</b> 轮\n· 时区：<code>Asia/Bangkok</code>\n\n请被抽中的同事留意 Telegram 私信中的质检通知与示例材料，并按提示完成确认与提交。	\N	UNDELIVERABLE	2026-04-12 08:40:09.610963+08	2026-04-12 08:40:11.418152+08	0	Telegram server says - Forbidden: bot was kicked from the supergroup chat	DONE
105	113	-1003767543777	3006	下班提醒：\n\n日期：2026-04-12\n部门：UXSJ\n班次：01:10 - 12:00\n时区：Asia/Bangkok\n\n本日工作时间已经结束，请各位同事不要忘记打卡，祝您生活愉快。	\N	SENT	2026-04-12 13:03:24.288649+08	2026-04-12 13:03:30.206215+08	0	\N	DONE
124	135	6332760420	3005	<a href="https://t.me/jeffery1836">test</a>领导您好，\n\n部门：UXSJ\n班次：13:00 — 22:00\n时区：Asia/Bangkok\n\n<a href="https://t.me/jeffery1836">test</a>组：应到岗3人，实际到岗0人，0人报备休假，3人未打卡	\N	SENT	2026-04-13 14:02:02.330198+08	2026-04-13 14:02:12.724057+08	0	\N	DONE
108	116	7625966687	3004	您负责的Asia/Bangkok 13:00 —— 22:00 的班次目前已经开始，应到岗18人，已到岗18人。	\N	SENT	2026-04-12 14:01:52.830326+08	2026-04-12 14:01:57.75839+08	0	\N	DONE
127	138	7348045344	3005	<a href="https://t.me/Sanverygoodli117">Sanchali</a>领导您好，\n\n部门：UXSJ\n班次：13:00 — 22:00\n时区：Asia/Bangkok\n\n<a href="https://t.me/Y_UX_Kairice">Kairice</a>组：应到岗9人，实际到岗9人，0人报备休假，0人未打卡\n<a href="https://t.me/Y_UX_Tanzaniju">tanzaniju</a>组：应到岗6人，实际到岗6人，0人报备休假，0人未打卡\n<a href="https://t.me/Y_UX_Aikantui">aikantui</a>组：应到岗3人，实际到岗3人，0人报备休假，0人未打卡	\N	SENT	2026-04-13 14:02:03.968069+08	2026-04-13 14:02:14.448352+08	0	\N	DONE
130	141	-1003883297177	2004	质检开启公告\n\n部门：UXSJ\n班次：13:00 — 22:00\n时区：Asia/Bangkok\n\n今日第3轮抽检已经开始，请以下成员留意本机器人私信并在15分钟内完成质检任务，质检结果将写入数据库。\n\nPadadgu\nXitanua\nGRENADA\n\nps：如果您未收到质检任务请私信机器人并发送指令 /qc ，可重启质检流程。	\N	SENT	2026-04-13 18:30:04.57284+08	2026-04-13 18:30:06.002351+08	0	\N	DONE
133	146	-1003767543777	3006	下班提醒：\n\n日期：2026-04-13\n部门：UXSJ\n班次：13:00 - 22:00\n时区：Asia/Bangkok\n\n本日工作时间已经结束，请各位同事不要忘记打卡，祝您生活愉快。	\N	SENT	2026-04-13 23:03:30.638067+08	2026-04-13 23:03:37.715297+08	0	\N	DONE
138	153	6332760420	3005	<a href="https://t.me/jeffery1836">test</a>领导您好，\n\n部门：UXSJ\n班次：13:00 — 22:00\n时区：Asia/Bangkok\n\n<a href="https://t.me/jeffery1836">test</a>组：应到岗3人，实际到岗0人，0人报备休假，3人未打卡	\N	SENT	2026-04-14 14:03:05.115597+08	2026-04-14 14:03:18.703407+08	0	\N	DONE
82	85	-1003767543777	1003	离岗报备公告\n\n姓名：test\n工号：7122\n部门：UXSJ\n日期：2026-04-11\n离岗时间：19:00-20:00\n离岗原因：嫖娼\n\n审批人：test	\N	SENT	2026-04-11 19:59:33.939853+08	2026-04-11 19:59:35.263872+08	0	\N	DONE
111	119	-1003883297177	2004	质检开启公告\n\n部门：UXSJ\n班次：13:00 — 22:00\n时区：Asia/Bangkok\n\n今日第2轮抽检已经开始，请以下成员留意本机器人私信并在15分钟内完成质检任务，质检结果将写入数据库。\n\nRapunzelli\naikantui\ntanzaniju\n\nps：如果您未收到质检任务请私信机器人并发送指令 /qc ，可重启质检流程。	\N	SENT	2026-04-12 16:30:05.715106+08	2026-04-12 16:30:06.111806+08	0	\N	DONE
85	89	6332760420	3005	<a href="https://t.me/jeffery1836">test</a>领导您好，\n\n部门：UXSJ\n班次：12:50 — 22:00\n时区：Asia/Bangkok\n\n<a href="https://t.me/jeffery1836">test</a>组：应到岗3人，实际到岗0人，0人报备休假，3人未打卡	\N	SENT	2026-04-11 20:02:37.615949+08	2026-04-11 20:02:53.728481+08	0	\N	DONE
113	122	-1003883297177	2004	质检开启公告\n\n部门：UXSJ\n班次：13:00 — 22:00\n时区：Asia/Bangkok\n\n今日第4轮抽检已经开始，请以下成员留意本机器人私信并在15分钟内完成质检任务，质检结果将写入数据库。\n\nPadadgu\nXitanua\nGRENADA\n\nps：如果您未收到质检任务请私信机器人并发送指令 /qc ，可重启质检流程。	\N	SENT	2026-04-12 20:30:06.376007+08	2026-04-12 20:30:07.162198+08	0	\N	DONE
88	93	7348045344	3005	<a href="https://t.me/Sanverygoodli117">Sanchali</a>领导您好，\n\n部门：UXSJ\n班次：13:00 — 22:00\n时区：Asia/Bangkok\n\n<a href="https://t.me/Y_UX_Kairice">Kairice</a>组：应到岗9人，实际到岗9人，0人报备休假，0人未打卡\n<a href="https://t.me/Y_UX_Tanzaniju">tanzaniju</a>组：应到岗6人，实际到岗5人，0人报备休假，1人未打卡\n<a href="https://t.me/Y_UX_Aikantui">aikantui</a>组：应到岗3人，实际到岗1人，0人报备休假，2人未打卡	\N	UNDELIVERABLE	2026-04-11 20:02:39.467975+08	2026-04-11 20:02:55.731383+08	0	Telegram server says - Bad Request: chat not found	DONE
91	96	-1003767543777	1003	离岗报备公告\n\n姓名：test\n工号：7122\n部门：UXSJ\n日期：2026-04-11\n离岗时间：21:25-21:30\n离岗原因：嘿嘿\n\n审批人：test	\N	SENT	2026-04-11 22:25:35.283795+08	2026-04-11 22:25:35.870809+08	0	\N	DONE
116	125	-1003883297177	2004	质检开启公告\n\n部门：UXSJ\n班次：13:00 — 22:00\n时区：Asia/Bangkok\n\n今日第5轮抽检已经开始，请以下成员留意本机器人私信并在15分钟内完成质检任务，质检结果将写入数据库。\n\nFoxieya\nBekahs\nNAYXUA\n\nps：如果您未收到质检任务请私信机器人并发送指令 /qc ，可重启质检流程。	\N	SENT	2026-04-12 22:30:02.215643+08	2026-04-12 22:30:02.584422+08	0	\N	DONE
94	100	-1003767543777	3003	开班考勤汇总：\n日期：2026-04-12\n部门：UXSJ\n班次：01:00 - 22:00\n时区：Asia/Bangkok\n部门负责人：<a href="https://t.me/jeffery1836">test</a>\n\n今日应到岗人数：3\n已到岗人数：0\n\n报备休假名单：0\n迟到名单：0\n未打卡名单：3\n- <a href="https://t.me/jeffery1836">test</a>\n- <a href="https://t.me/Y_TC_NOHHAEIL">NOHHAEIL</a>\n- <a href="https://t.me/Sanverygoodli117">Sanchali</a>\n\n质检即将启动，请留意通知。	\N	SENT	2026-04-12 02:02:56.791732+08	2026-04-12 02:03:02.006265+08	0	\N	DONE
119	128	-1003767543777	1003	离岗报备公告\n\n姓名：test\n工号：7122\n部门：UXSJ\n日期：2026-04-12\n离岗时间：21:40-21:50\n离岗原因：出门吃饭\n\n审批人：test	\N	SENT	2026-04-12 22:41:25.891267+08	2026-04-12 22:41:27.082147+08	0	\N	DONE
97	103	-1003767543777	2004	<b>QC round start (placeholder)</b>\nshift_id=0\nqc_round=1\n	\N	SENT	2026-04-12 02:15:04.655624+08	2026-04-12 02:15:05.155115+08	0	\N	DONE
100	106	-1003767543777	2004	<b>质检开启公告</b>\n本考勤群所绑定的班次已开启新一轮质检抽查。\n· 班次：<code>0</code>\n· 轮次：第 <b>2</b> 轮\n· 时区：<code>Asia/Bangkok</code>\n\n请被抽中的同事留意 Telegram 私信中的质检通知与示例材料，并按提示完成确认与提交。	\N	UNDELIVERABLE	2026-04-12 04:40:09.136736+08	2026-04-12 04:40:10.259902+08	0	Telegram server says - Forbidden: bot was kicked from the supergroup chat	DONE
122	133	-1003767543777	3003	开班考勤汇总：\n日期：2026-04-13\n部门：UXSJ\n班次：13:00 - 22:00\n时区：Asia/Bangkok\n部门负责人：<a href="https://t.me/jeffery1836">test</a>\n\n今日应到岗人数：3\n已到岗人数：0\n\n报备休假名单：0\n迟到名单：0\n未打卡名单：3\n- <a href="https://t.me/jeffery1836">test</a>\n- <a href="https://t.me/Y_TC_NOHHAEIL">NOHHAEIL</a>\n- <a href="https://t.me/Sanverygoodli117">Sanchali</a>\n\n质检即将启动，请留意通知。	\N	SENT	2026-04-13 14:02:02.330198+08	2026-04-13 14:02:11.706905+08	0	\N	DONE
103	110	-1003767543777	2004	<b>质检开启公告</b>\n本考勤群所绑定的班次已开启新一轮质检抽查。\n· 班次：<code>0</code>\n· 轮次：第 <b>5</b> 轮\n· 时区：<code>Asia/Bangkok</code>\n\n请被抽中的同事留意 Telegram 私信中的质检通知与示例材料，并按提示完成确认与提交。	\N	UNDELIVERABLE	2026-04-12 10:40:09.821096+08	2026-04-12 10:40:10.5686+08	0	Telegram server says - Forbidden: bot was kicked from the supergroup chat	DONE
125	136	-1003883297177	3003	开班考勤汇总：\n日期：2026-04-13\n部门：UXSJ\n班次：13:00 - 22:00\n时区：Asia/Bangkok\n部门负责人：<a href="https://t.me/Sanverygoodli117">Sanchali</a>\n\n今日应到岗人数：18\n已到岗人数：18\n\n报备休假名单：0\n迟到名单：0\n未打卡名单：0\n\n质检即将启动，请留意通知。	\N	SENT	2026-04-13 14:02:03.968069+08	2026-04-13 14:02:13.222831+08	0	\N	DONE
106	114	-1003767543777	2005	<b>质检班次汇总公告</b>\n日期：2026-04-12\n部门：UXSJ\n班次：01:10 — 12:00\n时区：Asia/Bangkok\n\n今日共质检1轮，质检覆盖人员及结果公示如下：\n\nNOHHAEIL：\n第6轮 未完成\n\nSanchali：\n第6轮 未完成\n\ntest：\n第6轮 未完成\n\n质检结果已经录入，如有问题请及时联系管理员。\n	\N	SENT	2026-04-12 13:10:00.558696+08	2026-04-12 13:10:02.28721+08	0	\N	DONE
109	117	7348045344	3005	<a href="https://t.me/Sanverygoodli117">Sanchali</a>领导您好，\n\n部门：UXSJ\n班次：13:00 — 22:00\n时区：Asia/Bangkok\n\n<a href="https://t.me/Y_UX_Kairice">Kairice</a>组：应到岗9人，实际到岗9人，0人报备休假，0人未打卡\n<a href="https://t.me/Y_UX_Tanzaniju">tanzaniju</a>组：应到岗6人，实际到岗6人，0人报备休假，0人未打卡\n<a href="https://t.me/Y_UX_Aikantui">aikantui</a>组：应到岗3人，实际到岗3人，0人报备休假，0人未打卡	\N	SENT	2026-04-12 14:01:52.830326+08	2026-04-12 14:02:00.317613+08	0	\N	DONE
128	139	-1003883297177	2004	质检开启公告\n\n部门：UXSJ\n班次：13:00 — 22:00\n时区：Asia/Bangkok\n\n今日第1轮抽检已经开始，请以下成员留意本机器人私信并在15分钟内完成质检任务，质检结果将写入数据库。\n\nKarina\nbrick\nBrucewillis\n\nps：如果您未收到质检任务请私信机器人并发送指令 /qc ，可重启质检流程。	\N	SENT	2026-04-13 14:30:02.723142+08	2026-04-13 14:30:05.446029+08	0	\N	DONE
134	147	-1003883297177	3006	下班提醒：\n\n日期：2026-04-13\n部门：UXSJ\n班次：13:00 - 22:00\n时区：Asia/Bangkok\n\n本日工作时间已经结束，请各位同事不要忘记打卡，祝您生活愉快。	\N	SENT	2026-04-13 23:03:31.754797+08	2026-04-13 23:03:39.081622+08	0	\N	DONE
114	123	6332760420	1001	<a href="https://t.me/jeffery1836">test</a> 申请休假，信息如下：\n\n英文名：test\n工号：7122\n部门：UXSJ\n休假类型：年假\n休假日期：2026-12-12 至 2026-12-15\n休假时长：4天\n申请备注：（无）\n\n请选择您的审批结果：	\N	SENT	2026-04-12 21:56:57.23834+08	2026-04-12 21:56:57.2904+08	0	\N	DONE
83	87	-1003767543777	3003	开班考勤汇总：\n日期：2026-04-11\n部门：UXSJ\n班次：12:50 - 22:00\n时区：Asia/Bangkok\n部门负责人：<a href="https://t.me/jeffery1836">test</a>\n\n今日应到岗人数：3\n已到岗人数：0\n\n报备休假名单：0\n迟到名单：0\n未打卡名单：3\n- <a href="https://t.me/jeffery1836">test</a>\n- <a href="https://t.me/Y_TC_NOHHAEIL">NOHHAEIL</a>\n- <a href="https://t.me/Sanverygoodli117">Sanchali</a>\n\n质检即将启动，请留意通知。	\N	SENT	2026-04-11 20:02:37.615949+08	2026-04-11 20:02:51.697147+08	0	\N	DONE
143	160	-1003883297177	3006	下班提醒：\n\n日期：2026-04-14\n部门：UXSJ\n班次：13:00 - 22:00\n时区：Asia/Bangkok\n\n本日工作时间已经结束，请各位同事不要忘记打卡，祝您生活愉快。	\N	SENT	2026-04-14 23:03:53.074021+08	2026-04-14 23:04:01.545321+08	0	\N	DONE
86	91	-1003883297177	3003	开班考勤汇总：\n日期：2026-04-11\n部门：UXSJ\n班次：13:00 - 22:00\n时区：Asia/Bangkok\n部门负责人：<a href="https://t.me/Sanverygoodli117">Sanchali</a>\n\n今日应到岗人数：18\n已到岗人数：15\n\n报备休假名单：0\n迟到名单：0\n未打卡名单：3\n- <a href="https://t.me/Y_UX_Brick">brick</a>\n- <a href="https://t.me/Y_UX_Aikantui">aikantui</a>\n- <a href="https://t.me/Y_UX_Nlgelito">Nlgelito</a>\n\n质检即将启动，请留意通知。	\N	UNDELIVERABLE	2026-04-11 20:02:39.467975+08	2026-04-11 20:02:54.257473+08	0	Telegram server says - Bad Request: chat not found	DONE
117	126	6332760420	1001	test 申请离岗报备，信息如下：\n\n工号：7122\n部门：UXSJ\n日期：2026-04-12\n离岗时间：21:40-21:50\n离岗原因：出门吃饭\n\n请审批这条离岗申请	\N	SENT	2026-04-12 22:40:34.447706+08	2026-04-12 22:40:34.68678+08	0	\N	DONE
89	94	6332760420	1001	test 申请离岗报备，信息如下：\n\n工号：7122\n部门：UXSJ\n日期：2026-04-11\n离岗时间：21:25-21:30\n离岗原因：嘿嘿\n\n请审批这条离岗申请	\N	SENT	2026-04-11 22:25:30.148395+08	2026-04-11 22:25:30.604946+08	0	\N	DONE
92	97	-1003767543777	3006	下班提醒：\n\n日期：2026-04-11\n部门：UXSJ\n班次：12:50 - 22:00\n时区：Asia/Bangkok\n\n本日工作时间已经结束，请各位同事不要忘记打卡，祝您生活愉快。	\N	SENT	2026-04-11 23:00:03.104175+08	2026-04-11 23:00:04.997837+08	0	\N	DONE
120	129	-1003883297177	3006	下班提醒：\n\n日期：2026-04-12\n部门：UXSJ\n班次：13:00 - 22:00\n时区：Asia/Bangkok\n\n本日工作时间已经结束，请各位同事不要忘记打卡，祝您生活愉快。	\N	SENT	2026-04-12 23:00:08.720505+08	2026-04-12 23:00:13.168897+08	0	\N	DONE
95	101	6332760420	3004	您负责的Asia/Bangkok 01:00 —— 22:00 的班次目前已经开始，应到岗3人，已到岗0人。\n\n以下成员应到岗但仍未打卡，请确认员工状态：\n<a href="https://t.me/jeffery1836">test</a>\n<a href="https://t.me/Y_TC_NOHHAEIL">NOHHAEIL</a>\n<a href="https://t.me/Sanverygoodli117">Sanchali</a>	\N	SENT	2026-04-12 02:02:56.791732+08	2026-04-12 02:03:02.900137+08	0	\N	DONE
98	104	-1003767543777	2004	<b>QC round start (placeholder)</b>\nshift_id=0\nqc_round=1\n	\N	SENT	2026-04-12 02:20:10.58798+08	2026-04-12 02:20:11.923217+08	0	\N	DONE
123	134	6332760420	3004	您负责的Asia/Bangkok 13:00 —— 22:00 的班次目前已经开始，应到岗3人，已到岗0人。\n\n以下成员应到岗但仍未打卡，请确认员工状态：\n<a href="https://t.me/jeffery1836">test</a>\n<a href="https://t.me/Y_TC_NOHHAEIL">NOHHAEIL</a>\n<a href="https://t.me/Sanverygoodli117">Sanchali</a>	\N	SENT	2026-04-13 14:02:02.330198+08	2026-04-13 14:02:12.220861+08	0	\N	DONE
101	107	-1003767543777	2004	<b>质检开启公告</b>\n本考勤群所绑定的班次已开启新一轮质检抽查。\n· 班次：<code>0</code>\n· 轮次：第 <b>3</b> 轮\n· 时区：<code>Asia/Bangkok</code>\n\n请被抽中的同事留意 Telegram 私信中的质检通知与示例材料，并按提示完成确认与提交。	\N	UNDELIVERABLE	2026-04-12 06:40:00.92831+08	2026-04-12 06:40:01.453432+08	0	Telegram server says - Forbidden: bot was kicked from the supergroup chat	DONE
126	137	7625966687	3004	您负责的Asia/Bangkok 13:00 —— 22:00 的班次目前已经开始，应到岗18人，已到岗18人。	\N	SENT	2026-04-13 14:02:03.968069+08	2026-04-13 14:02:13.919495+08	0	\N	DONE
104	112	-1003767543777	2004	<b>质检开启公告</b>\n本考勤群所绑定的班次已开启新一轮质检抽查。\n· 班次：<code>0</code>\n· 轮次：第 <b>6</b> 轮\n· 时区：<code>Asia/Bangkok</code>\n\n请被抽中的同事留意 Telegram 私信中的质检通知与示例材料，并按提示完成确认与提交。	\N	SENT	2026-04-12 12:40:01.372093+08	2026-04-12 12:40:02.918362+08	0	\N	DONE
80	83	6332760420	1001	test 申请离岗报备，信息如下：\n\n工号：7122\n部门：UXSJ\n日期：2026-04-11\n离岗时间：19:00-20:00\n离岗原因：嫖娼\n\n请审批这条离岗申请	\N	SENT	2026-04-11 19:59:26.844536+08	2026-04-11 19:59:27.514158+08	0	\N	DONE
129	140	-1003883297177	2004	质检开启公告\n\n部门：UXSJ\n班次：13:00 — 22:00\n时区：Asia/Bangkok\n\n今日第2轮抽检已经开始，请以下成员留意本机器人私信并在15分钟内完成质检任务，质检结果将写入数据库。\n\nRapunzelli\nNlgelito\nSingjang\n\nps：如果您未收到质检任务请私信机器人并发送指令 /qc ，可重启质检流程。	\N	SENT	2026-04-13 16:30:03.688715+08	2026-04-13 16:30:05.472425+08	0	\N	DONE
107	115	-1003883297177	3003	开班考勤汇总：\n日期：2026-04-12\n部门：UXSJ\n班次：13:00 - 22:00\n时区：Asia/Bangkok\n部门负责人：<a href="https://t.me/Sanverygoodli117">Sanchali</a>\n\n今日应到岗人数：18\n已到岗人数：18\n\n报备休假名单：0\n迟到名单：0\n未打卡名单：0\n\n质检即将启动，请留意通知。	\N	SENT	2026-04-12 14:01:52.830326+08	2026-04-12 14:01:56.629234+08	0	\N	DONE
131	144	-1003883297177	2004	质检开启公告\n\n部门：UXSJ\n班次：13:00 — 22:00\n时区：Asia/Bangkok\n\n今日第4轮抽检已经开始，请以下成员留意本机器人私信并在15分钟内完成质检任务，质检结果将写入数据库。\n\nFoxieya\nBekahs\nNAYXUA\n\nps：如果您未收到质检任务请私信机器人并发送指令 /qc ，可重启质检流程。	\N	SENT	2026-04-13 20:30:05.986289+08	2026-04-13 20:30:06.653425+08	0	\N	DONE
132	145	-1003883297177	2004	质检开启公告\n\n部门：UXSJ\n班次：13:00 — 22:00\n时区：Asia/Bangkok\n\n今日第5轮抽检已经开始，请以下成员留意本机器人私信并在15分钟内完成质检任务，质检结果将写入数据库。\n\nKuroni\nYiliaza\nKarina\n\nps：如果您未收到质检任务请私信机器人并发送指令 /qc ，可重启质检流程。	\N	SENT	2026-04-13 22:30:04.36208+08	2026-04-13 22:30:05.790469+08	0	\N	DONE
137	152	6332760420	3004	您负责的Asia/Bangkok 13:00 —— 22:00 的班次目前已经开始，应到岗3人，已到岗0人。\n\n以下成员应到岗但仍未打卡，请确认员工状态：\n<a href="https://t.me/jeffery1836">test</a>\n<a href="https://t.me/Y_TC_NOHHAEIL">NOHHAEIL</a>\n<a href="https://t.me/Sanverygoodli117">Sanchali</a>	\N	SENT	2026-04-14 14:03:05.115597+08	2026-04-14 14:03:18.210786+08	0	\N	DONE
135	148	-1003883297177	2005	<b>质检班次汇总公告</b>\n日期：2026-04-13\n部门：UXSJ\n班次：13:00 — 22:00\n时区：Asia/Bangkok\n\n今日共质检5轮，质检结果如下：\n\n第1轮：\n完成：Karina\n未完成：brick、Brucewillis\n\n第2轮：\n完成：Nlgelito、Singjang\n未完成：Rapunzelli\n\n第3轮：\n完成：Padadgu、Xitanua、GRENADA\n未完成：无\n\n第4轮：\n完成：无\n未完成：Foxieya、Bekahs、NAYXUA\n\n第5轮：\n完成：Karina、Yiliaza\n未完成：Kuroni\n\n质检结果已经录入，如有问题请及时联系管理员。\n	\N	SENT	2026-04-13 23:10:06.831679+08	2026-04-13 23:10:08.477464+08	0	\N	DONE
142	159	-1003767543777	3006	下班提醒：\n\n日期：2026-04-14\n部门：UXSJ\n班次：13:00 - 22:00\n时区：Asia/Bangkok\n\n本日工作时间已经结束，请各位同事不要忘记打卡，祝您生活愉快。	\N	SENT	2026-04-14 23:03:52.351398+08	2026-04-14 23:04:01.023516+08	0	\N	DONE
136	151	-1003767543777	3003	开班考勤汇总：\n日期：2026-04-14\n部门：UXSJ\n班次：13:00 - 22:00\n时区：Asia/Bangkok\n部门负责人：<a href="https://t.me/jeffery1836">test</a>\n\n今日应到岗人数：3\n已到岗人数：0\n\n报备休假名单：0\n迟到名单：0\n未打卡名单：3\n- <a href="https://t.me/jeffery1836">test</a>\n- <a href="https://t.me/Y_TC_NOHHAEIL">NOHHAEIL</a>\n- <a href="https://t.me/Sanverygoodli117">Sanchali</a>\n\n质检即将启动，请留意通知。	\N	SENT	2026-04-14 14:03:05.115597+08	2026-04-14 14:03:15.953129+08	0	\N	DONE
139	154	-1003883297177	3003	开班考勤汇总：\n日期：2026-04-14\n部门：UXSJ\n班次：13:00 - 22:00\n时区：Asia/Bangkok\n部门负责人：<a href="https://t.me/Sanverygoodli117">Sanchali</a>\n\n今日应到岗人数：18\n已到岗人数：14\n\n报备休假名单：0\n迟到名单：0\n未打卡名单：4\n- <a href="https://t.me/Y_UX_Xitanua">Xitanua</a>\n- <a href="https://t.me/Y_UX_Grenada">GRENADA</a>\n- <a href="https://t.me/Y_UX_Kuroni">Kuroni</a>\n- <a href="https://t.me/Y_UX_Yiliaza">Yiliaza</a>\n\n质检即将启动，请留意通知。	\N	SENT	2026-04-14 14:03:06.96786+08	2026-04-14 14:03:19.170085+08	0	\N	DONE
140	155	7625966687	3004	您负责的Asia/Bangkok 13:00 —— 22:00 的班次目前已经开始，应到岗18人，已到岗14人。\n\n以下成员应到岗但仍未打卡，请确认员工状态：\n<a href="https://t.me/Y_UX_Xitanua">Xitanua</a>\n<a href="https://t.me/Y_UX_Grenada">GRENADA</a>\n<a href="https://t.me/Y_UX_Kuroni">Kuroni</a>\n<a href="https://t.me/Y_UX_Yiliaza">Yiliaza</a>	\N	SENT	2026-04-14 14:03:06.96786+08	2026-04-14 14:03:19.652046+08	0	\N	DONE
144	162	-1003767543777	3003	开班考勤汇总：\n日期：2026-04-19\n部门：UXSJ\n班次：13:00 - 22:00\n时区：Asia/Bangkok\n部门负责人：<a href="https://t.me/jeffery1836">test</a>\n\n今日应到岗人数：3\n已到岗人数：0\n\n报备休假名单：0\n迟到名单：0\n未打卡名单：3\n- <a href="https://t.me/jeffery1836">test</a>\n- <a href="https://t.me/Y_TC_NOHHAEIL">NOHHAEIL</a>\n- <a href="https://t.me/Sanverygoodli117">Sanchali</a>\n\n质检即将启动，请留意通知。	\N	SENT	2026-04-19 14:32:27.338861+08	2026-04-19 14:32:44.822477+08	0	\N	DONE
141	156	7348045344	3005	<a href="https://t.me/Sanverygoodli117">Sanchali</a>领导您好，\n\n部门：UXSJ\n班次：13:00 — 22:00\n时区：Asia/Bangkok\n\n<a href="https://t.me/Y_UX_Kairice">Kairice</a>组：应到岗9人，实际到岗7人，0人报备休假，2人未打卡\n<a href="https://t.me/Y_UX_Tanzaniju">tanzaniju</a>组：应到岗6人，实际到岗4人，0人报备休假，2人未打卡\n<a href="https://t.me/Y_UX_Aikantui">aikantui</a>组：应到岗3人，实际到岗3人，0人报备休假，0人未打卡	\N	SENT	2026-04-14 14:03:06.96786+08	2026-04-14 14:03:20.14977+08	0	\N	DONE
145	163	6332760420	3004	您负责的Asia/Bangkok 13:00 —— 22:00 的班次目前已经开始，应到岗3人，已到岗0人。\n\n以下成员应到岗但仍未打卡，请确认员工状态：\n<a href="https://t.me/jeffery1836">test</a>\n<a href="https://t.me/Y_TC_NOHHAEIL">NOHHAEIL</a>\n<a href="https://t.me/Sanverygoodli117">Sanchali</a>	\N	SENT	2026-04-19 14:32:27.338861+08	2026-04-19 14:32:45.700431+08	0	\N	DONE
146	164	6332760420	3005	<a href="https://t.me/jeffery1836">test</a>领导您好，\n\n部门：UXSJ\n班次：13:00 — 22:00\n时区：Asia/Bangkok\n\n<a href="https://t.me/jeffery1836">test</a>组：应到岗3人，实际到岗0人，0人报备休假，3人未打卡	\N	SENT	2026-04-19 14:32:27.338861+08	2026-04-19 14:32:46.840236+08	0	\N	DONE
148	167	7625966687	3004	您负责的Asia/Bangkok 13:00 —— 22:00 的班次目前已经开始，应到岗18人，已到岗0人。\n\n以下成员应到岗但仍未打卡，请确认员工状态：\n<a href="https://t.me/Y_UX_Jindiao">JINDIAO</a>\n<a href="https://t.me/Y_UX_Karina">Karina</a>\n<a href="https://t.me/Y_UX_Brick">brick</a>\n<a href="https://t.me/Y_UX_Brucewillis">Brucewillis</a>\n<a href="https://t.me/Y_UX_Rapunzelli1">Rapunzelli</a>\n<a href="https://t.me/Y_UX_Aikantui">aikantui</a>\n<a href="https://t.me/Y_UX_Tanzaniju">tanzaniju</a>\n<a href="https://t.me/Y_UX_Kairice">Kairice</a>\n<a href="https://t.me/Y_UX_Nlgelito">Nlgelito</a>\n<a href="https://t.me/Y_UX_Singjang">Singjang</a>\n<a href="https://t.me/Y_UX_Padadgu">Padadgu</a>\n<a href="https://t.me/Y_UX_Xitanua">Xitanua</a>\n<a href="https://t.me/Y_UX_Grenada">GRENADA</a>\n<a href="https://t.me/Y_UX_Foxieya">Foxieya</a>\n<a href="https://t.me/Y_UX_Bekahs">Bekahs</a>\n<a href="https://t.me/Y_UX_Nayxua">NAYXUA</a>\n<a href="https://t.me/Y_UX_Kuroni">Kuroni</a>\n<a href="https://t.me/Y_UX_Yiliaza">Yiliaza</a>	\N	SENT	2026-04-19 14:32:29.577716+08	2026-04-19 14:32:50.968553+08	0	\N	DONE
149	168	7348045344	3005	<a href="https://t.me/Sanverygoodli117">Sanchali</a>领导您好，\n\n部门：UXSJ\n班次：13:00 — 22:00\n时区：Asia/Bangkok\n\n<a href="https://t.me/Y_UX_Kairice">Kairice</a>组：应到岗9人，实际到岗0人，0人报备休假，9人未打卡\n<a href="https://t.me/Y_UX_Tanzaniju">tanzaniju</a>组：应到岗6人，实际到岗0人，0人报备休假，6人未打卡\n<a href="https://t.me/Y_UX_Aikantui">aikantui</a>组：应到岗3人，实际到岗0人，0人报备休假，3人未打卡	\N	SENT	2026-04-19 14:32:29.577716+08	2026-04-19 14:32:51.446465+08	0	\N	DONE
150	171	-1003767543777	3006	下班提醒：\n\n日期：2026-04-19\n部门：UXSJ\n班次：13:00 - 22:00\n时区：Asia/Bangkok\n\n本日工作时间已经结束，请各位同事不要忘记打卡，祝您生活愉快。	\N	SENT	2026-04-19 23:03:15.246391+08	2026-04-19 23:03:25.696539+08	0	\N	DONE
151	172	-1003883297177	3006	下班提醒：\n\n日期：2026-04-19\n部门：UXSJ\n班次：13:00 - 22:00\n时区：Asia/Bangkok\n\n本日工作时间已经结束，请各位同事不要忘记打卡，祝您生活愉快。	\N	SENT	2026-04-19 23:03:16.500597+08	2026-04-19 23:03:26.3739+08	0	\N	DONE
154	176	6332760420	3005	<a href="https://t.me/jeffery1836">test</a>领导您好，\n\n部门：UXSJ\n班次：13:00 — 22:00\n时区：Asia/Bangkok\n\n<a href="https://t.me/jeffery1836">test</a>组：应到岗3人，实际到岗0人，0人报备休假，3人未打卡	\N	SENT	2026-04-30 19:08:47.392287+08	2026-04-30 19:09:07.650966+08	0	\N	DONE
147	166	-1003883297177	3003	开班考勤汇总：\n日期：2026-04-19\n部门：UXSJ\n班次：13:00 - 22:00\n时区：Asia/Bangkok\n部门负责人：<a href="https://t.me/Sanverygoodli117">Sanchali</a>\n\n今日应到岗人数：18\n已到岗人数：0\n\n报备休假名单：0\n迟到名单：0\n未打卡名单：18\n- <a href="https://t.me/Y_UX_Jindiao">JINDIAO</a>\n- <a href="https://t.me/Y_UX_Karina">Karina</a>\n- <a href="https://t.me/Y_UX_Brick">brick</a>\n- <a href="https://t.me/Y_UX_Brucewillis">Brucewillis</a>\n- <a href="https://t.me/Y_UX_Rapunzelli1">Rapunzelli</a>\n- <a href="https://t.me/Y_UX_Aikantui">aikantui</a>\n- <a href="https://t.me/Y_UX_Tanzaniju">tanzaniju</a>\n- <a href="https://t.me/Y_UX_Kairice">Kairice</a>\n- <a href="https://t.me/Y_UX_Nlgelito">Nlgelito</a>\n- <a href="https://t.me/Y_UX_Singjang">Singjang</a>\n- <a href="https://t.me/Y_UX_Padadgu">Padadgu</a>\n- <a href="https://t.me/Y_UX_Xitanua">Xitanua</a>\n- <a href="https://t.me/Y_UX_Grenada">GRENADA</a>\n- <a href="https://t.me/Y_UX_Foxieya">Foxieya</a>\n- <a href="https://t.me/Y_UX_Bekahs">Bekahs</a>\n- <a href="https://t.me/Y_UX_Nayxua">NAYXUA</a>\n- <a href="https://t.me/Y_UX_Kuroni">Kuroni</a>\n- <a href="https://t.me/Y_UX_Yiliaza">Yiliaza</a>\n\n质检即将启动，请留意通知。	\N	SENT	2026-04-19 14:32:29.577716+08	2026-04-19 14:32:50.485192+08	0	\N	DONE
152	174	-1003767543777	3003	开班考勤汇总：\n日期：2026-04-30\n部门：UXSJ\n班次：13:00 - 22:00\n时区：Asia/Bangkok\n部门负责人：<a href="https://t.me/jeffery1836">test</a>\n\n今日应到岗人数：3\n已到岗人数：0\n\n报备休假名单：0\n迟到名单：0\n未打卡名单：3\n- <a href="https://t.me/jeffery1836">test</a>\n- <a href="https://t.me/Y_TC_NOHHAEIL">NOHHAEIL</a>\n- <a href="https://t.me/Sanverygoodli117">Sanchali</a>\n\n质检即将启动，请留意通知。	\N	SENT	2026-04-30 19:08:47.392287+08	2026-04-30 19:09:05.752769+08	0	\N	DONE
155	178	-1003883297177	3003	开班考勤汇总：\n日期：2026-04-30\n部门：UXSJ\n班次：13:00 - 22:00\n时区：Asia/Bangkok\n部门负责人：<a href="https://t.me/Sanverygoodli117">Sanchali</a>\n\n今日应到岗人数：18\n已到岗人数：0\n\n报备休假名单：0\n迟到名单：0\n未打卡名单：18\n- <a href="https://t.me/Y_UX_Jindiao">JINDIAO</a>\n- <a href="https://t.me/Y_UX_Karina">Karina</a>\n- <a href="https://t.me/Y_UX_Brick">brick</a>\n- <a href="https://t.me/Y_UX_Brucewillis">Brucewillis</a>\n- <a href="https://t.me/Y_UX_Rapunzelli1">Rapunzelli</a>\n- <a href="https://t.me/Y_UX_Aikantui">aikantui</a>\n- <a href="https://t.me/Y_UX_Tanzaniju">tanzaniju</a>\n- <a href="https://t.me/Y_UX_Kairice">Kairice</a>\n- <a href="https://t.me/Y_UX_Nlgelito">Nlgelito</a>\n- <a href="https://t.me/Y_UX_Singjang">Singjang</a>\n- <a href="https://t.me/Y_UX_Padadgu">Padadgu</a>\n- <a href="https://t.me/Y_UX_Xitanua">Xitanua</a>\n- <a href="https://t.me/Y_UX_Grenada">GRENADA</a>\n- <a href="https://t.me/Y_UX_Foxieya">Foxieya</a>\n- <a href="https://t.me/Y_UX_Bekahs">Bekahs</a>\n- <a href="https://t.me/Y_UX_Nayxua">NAYXUA</a>\n- <a href="https://t.me/Y_UX_Kuroni">Kuroni</a>\n- <a href="https://t.me/Y_UX_Yiliaza">Yiliaza</a>\n\n质检即将启动，请留意通知。	\N	SENT	2026-04-30 19:08:49.079729+08	2026-04-30 19:09:11.642592+08	0	\N	DONE
156	179	7625966687	3004	您负责的Asia/Bangkok 13:00 —— 22:00 的班次目前已经开始，应到岗18人，已到岗0人。\n\n以下成员应到岗但仍未打卡，请确认员工状态：\n<a href="https://t.me/Y_UX_Jindiao">JINDIAO</a>\n<a href="https://t.me/Y_UX_Karina">Karina</a>\n<a href="https://t.me/Y_UX_Brick">brick</a>\n<a href="https://t.me/Y_UX_Brucewillis">Brucewillis</a>\n<a href="https://t.me/Y_UX_Rapunzelli1">Rapunzelli</a>\n<a href="https://t.me/Y_UX_Aikantui">aikantui</a>\n<a href="https://t.me/Y_UX_Tanzaniju">tanzaniju</a>\n<a href="https://t.me/Y_UX_Kairice">Kairice</a>\n<a href="https://t.me/Y_UX_Nlgelito">Nlgelito</a>\n<a href="https://t.me/Y_UX_Singjang">Singjang</a>\n<a href="https://t.me/Y_UX_Padadgu">Padadgu</a>\n<a href="https://t.me/Y_UX_Xitanua">Xitanua</a>\n<a href="https://t.me/Y_UX_Grenada">GRENADA</a>\n<a href="https://t.me/Y_UX_Foxieya">Foxieya</a>\n<a href="https://t.me/Y_UX_Bekahs">Bekahs</a>\n<a href="https://t.me/Y_UX_Nayxua">NAYXUA</a>\n<a href="https://t.me/Y_UX_Kuroni">Kuroni</a>\n<a href="https://t.me/Y_UX_Yiliaza">Yiliaza</a>	\N	SENT	2026-04-30 19:08:49.079729+08	2026-04-30 19:09:12.1542+08	0	\N	DONE
157	180	7348045344	3005	<a href="https://t.me/Sanverygoodli117">Sanchali</a>领导您好，\n\n部门：UXSJ\n班次：13:00 — 22:00\n时区：Asia/Bangkok\n\n<a href="https://t.me/Y_UX_Kairice">Kairice</a>组：应到岗9人，实际到岗0人，0人报备休假，9人未打卡\n<a href="https://t.me/Y_UX_Tanzaniju">tanzaniju</a>组：应到岗6人，实际到岗0人，0人报备休假，6人未打卡\n<a href="https://t.me/Y_UX_Aikantui">aikantui</a>组：应到岗3人，实际到岗0人，0人报备休假，3人未打卡	\N	SENT	2026-04-30 19:08:49.079729+08	2026-04-30 19:09:12.633214+08	0	\N	DONE
153	175	6332760420	3004	您负责的Asia/Bangkok 13:00 —— 22:00 的班次目前已经开始，应到岗3人，已到岗0人。\n\n以下成员应到岗但仍未打卡，请确认员工状态：\n<a href="https://t.me/jeffery1836">test</a>\n<a href="https://t.me/Y_TC_NOHHAEIL">NOHHAEIL</a>\n<a href="https://t.me/Sanverygoodli117">Sanchali</a>	\N	SENT	2026-04-30 19:08:47.392287+08	2026-04-30 19:09:06.670105+08	0	\N	DONE
\.


--
-- TOC entry 5280 (class 0 OID 17821)
-- Dependencies: 220
-- Data for Name: organizations; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.organizations (id, department_name, highest_responsible_employee_id, leader_employee_id) FROM stdin;
1	UXSJ	51964	56753
2	UXSJ	51964	55516
3	UXSJ	51964	31088
0	UXSJ	7122	7122
\.


--
-- TOC entry 5298 (class 0 OID 17905)
-- Dependencies: 238
-- Data for Name: qc_exemption_fixed_list; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.qc_exemption_fixed_list (id, shift_id, employee_id, remark) FROM stdin;
2	1	56753	大米
3	1	55516	阿哲
4	1	31088	爱看腿
5	1	29337	乐佩
6	1	72494	管理员
\.


--
-- TOC entry 5304 (class 0 OID 17931)
-- Dependencies: 244
-- Data for Name: qc_results; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.qc_results (id, employee_id, shift_id, organization_id, qc_date, qc_round, checked_at, completed_at, result, attachment_id) FROM stdin;
16	7122	0	0	2026-04-12	6	2026-04-12 12:55:10.348816+08	2026-04-12 12:55:10.348816+08	TIMEOUT	\N
17	51761	0	0	2026-04-12	6	2026-04-12 12:55:10.348816+08	2026-04-12 12:55:10.348816+08	TIMEOUT	\N
18	51964	0	0	2026-04-12	6	2026-04-12 12:55:10.348816+08	2026-04-12 12:55:10.348816+08	TIMEOUT	\N
19	17025	1	1	2026-04-12	1	2026-04-12 14:33:18.567935+08	2026-04-12 14:33:18.567935+08	PASS	AgACAgUAAxkBAAIHZGnbPKowH6_eY-oO8cAEax10NglOAALEDWsbmEzgVjplXFA0VnqHAQADAgADeQADOwQ
20	31088	1	3	2026-04-12	2	2026-04-12 16:31:45.854548+08	2026-04-12 16:31:45.854548+08	PASS	AgACAgUAAxkBAAIHamnbWFfiLMjHv0piMuMbUE-JVIDzAAIgDWsbmfrZVinDmItNlWGuAQADAgADeQADOwQ
21	55516	1	2	2026-04-12	2	2026-04-12 16:45:22.041697+08	2026-04-12 16:45:22.041697+08	TIMEOUT	\N
22	56773	1	1	2026-04-12	3	2026-04-12 18:38:00.938924+08	2026-04-12 18:38:00.938924+08	PASS	AgACAgUAAxkBAAIHdWnbdgY1mcANZT0tGSVSv0WZDGZtAAIGD2sbqDnZVkHrL1dPaN2gAQADAgADeQADOwQ
23	56759	1	3	2026-04-12	3	2026-04-12 18:38:17.392425+08	2026-04-12 18:38:17.392425+08	PASS	AgACAgUAAxkBAAIHeGnbdhX-u5IWIQMMbAWo1inWm9FrAAIJD2sbd_7YVuGaXEhUdG2qAQADAgADeQADOwQ
24	56753	1	1	2026-04-12	3	2026-04-12 18:51:38.637102+08	2026-04-12 18:51:38.637102+08	TIMEOUT	\N
25	58073	1	1	2026-04-12	4	2026-04-12 20:30:58.882681+08	2026-04-12 20:30:58.882681+08	PASS	AgACAgUAAxkBAAIHfWnbkH9-ETZQXTEgV722fGNxgke-AAKGDmsbINngVspt2rsnRUWdAQADAgADeQADOwQ
26	72357	1	2	2026-04-12	4	2026-04-12 20:38:13.308243+08	2026-04-12 20:38:13.308243+08	PASS	AgACAgUAAxkBAAIHh2nbkjELgGCVH0ZEvXsuTpcENHF9AAKLEWsb4UjYViwTfe1dR-52AQADAgADeQADOwQ
27	59242	1	2	2026-04-12	4	2026-04-12 20:40:47.692148+08	2026-04-12 20:40:47.692148+08	PASS	AgACAgUAAxkBAAIHjGnbksIpeDRtNLdzx7PcwaI4y-nVAAKzDmsbtmfhVk05m-6ABAGfAQADAgADeQADOwQ
28	74114	1	2	2026-04-12	5	2026-04-12 22:33:34.227238+08	2026-04-12 22:33:34.227238+08	PASS	AgACAgUAAxkBAAIHuWnbrTSXVKb7-ID9K9oB8dih4iTqAAKADWsb4nfgVhqxWk0_eyo7AQADAgADeQADOwQ
29	4257	1	2	2026-04-13	1	2026-04-13 14:32:57.91562+08	2026-04-13 14:32:57.91562+08	PASS	AgACAgUAAxkBAAIH8Gncjg70YvS9h-NBYzBw_QQZo8NnAAKgD2sbxvPoVho3xwpQxu0vAQADAgADeQADOwQ
30	17025	1	1	2026-04-13	1	2026-04-13 14:43:31.507474+08	2026-04-13 14:43:31.507474+08	FAIL	\N
31	4257	1	2	2026-04-12	1	2026-04-13 14:46:13.470438+08	2026-04-13 14:46:13.470438+08	TIMEOUT	\N
32	16908	1	2	2026-04-12	1	2026-04-13 14:52:24.989151+08	2026-04-13 14:52:24.989151+08	PASS	AgACAgUAAxkBAAIH-2nckqIXODtSfsV21A_e92_nCr84AAJaDWsb-rPhVqIRPT7iRD1GAQADAgADeQADOwQ
33	16908	1	2	2026-04-13	1	2026-04-13 14:53:02.895885+08	2026-04-13 14:53:02.895885+08	TIMEOUT	\N
34	29337	1	1	2026-04-12	2	2026-04-13 16:25:39.421989+08	2026-04-13 16:25:39.421989+08	TIMEOUT	\N
35	74168	1	3	2026-04-12	5	2026-04-13 16:25:39.421989+08	2026-04-13 16:25:39.421989+08	TIMEOUT	\N
36	74306	1	1	2026-04-12	5	2026-04-13 16:25:39.421989+08	2026-04-13 16:25:39.421989+08	TIMEOUT	\N
37	56773	1	1	2026-04-13	2	2026-04-13 16:31:11.498859+08	2026-04-13 16:31:11.498859+08	PASS	AgACAgUAAxkBAAIIAmncqc3wn5q14Ke0_j5DhkzyWTiVAAKXDmsb13DhVg3NBO2FVymzAQADAgADeQADOwQ
38	56759	1	3	2026-04-13	2	2026-04-13 16:31:33.931655+08	2026-04-13 16:31:33.931655+08	PASS	AgACAgUAAxkBAAIIBWncqeJZvZgx-TUTAsBW99xqPii6AAKqEWsbMCfoVr1MZRwNcTTxAQADAgADeQADOwQ
39	29337	1	1	2026-04-13	2	2026-04-13 16:45:11.713467+08	2026-04-13 16:45:11.713467+08	TIMEOUT	\N
40	58073	1	1	2026-04-13	3	2026-04-13 18:30:47.741024+08	2026-04-13 18:30:47.741024+08	PASS	AgACAgUAAxkBAAIIDWncxdR4aG_td_T6guUTON5ELoXgAAKfDmsb_OXoVilEZiAIUIAaAQADAgADeQADOwQ
41	59242	1	2	2026-04-13	3	2026-04-13 18:31:01.765031+08	2026-04-13 18:31:01.765031+08	PASS	AgACAgUAAxkBAAIIEGncxeOMkRurv4oDvV-GhngWzHPYAALxDmsbCd7oVpcoR7M8wfNBAQADAgADeQADOwQ
42	72357	1	2	2026-04-13	3	2026-04-13 18:35:52.883383+08	2026-04-13 18:35:52.883383+08	PASS	AgACAgUAAxkBAAIIE2ncxvvNpiTHZ-kWo9AGPhvaa1-BAALRD2sboozpVh5Rx4Myc3K5AQADAgADeQADOwQ
43	74114	1	2	2026-04-13	4	2026-04-13 20:45:12.842301+08	2026-04-13 20:45:12.842301+08	TIMEOUT	\N
44	74168	1	3	2026-04-13	4	2026-04-13 20:45:12.842301+08	2026-04-13 20:45:12.842301+08	TIMEOUT	\N
45	74306	1	1	2026-04-13	4	2026-04-13 20:45:12.842301+08	2026-04-13 20:45:12.842301+08	TIMEOUT	\N
46	74322	1	1	2026-04-13	5	2026-04-13 22:31:07.789806+08	2026-04-13 22:31:07.789806+08	PASS	AgACAgUAAxkBAAIIKWnc_iEh0_c3-Jm2Akg5Lf6w6obyAAIcD2sb8CvpVgmmoT-oSWkDAQADAgADeQADOwQ
47	4257	1	2	2026-04-13	5	2026-04-13 22:32:13.39565+08	2026-04-13 22:32:13.39565+08	PASS	AgACAgUAAxkBAAIILWnc_mpKMYSh1jY_L0Lec9_aApWzAAIjDWsbk-3oVnejqT9lkeCYAQADAgADeQADOwQ
48	74314	1	1	2026-04-13	5	2026-04-13 22:45:14.666247+08	2026-04-13 22:45:14.666247+08	TIMEOUT	\N
\.


--
-- TOC entry 5312 (class 0 OID 17973)
-- Dependencies: 252
-- Data for Name: qc_task_queue; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.qc_task_queue (id, log_id, employee_id, shift_id, qc_date, qc_round, status, task_result, created_at, processed_at, retry_count, error_message, first_private_notify_sent_at, pending_confirm_file_id) FROM stdin;
22	112	7122	0	2026-04-12	6	TIMEOUT	TIMEOUT	2026-04-12 12:40:01.372093+08	\N	0	\N	2026-04-12 12:40:05.924781+08	\N
23	112	51761	0	2026-04-12	6	TIMEOUT	TIMEOUT	2026-04-12 12:40:01.372093+08	\N	0	\N	2026-04-12 12:40:06.678968+08	\N
24	112	51964	0	2026-04-12	6	TIMEOUT	TIMEOUT	2026-04-12 12:40:01.372093+08	\N	0	\N	2026-04-12 12:40:07.504723+08	\N
27	118	17025	1	2026-04-12	1	COMPLETED	PASS	2026-04-12 14:30:05.357254+08	\N	0	\N	2026-04-12 14:30:09.412745+08	AgACAgUAAxkBAAIHZGnbPKowH6_eY-oO8cAEax10NglOAALEDWsbmEzgVjplXFA0VnqHAQADAgADeQADOwQ
45	140	56773	1	2026-04-13	2	COMPLETED	PASS	2026-04-13 16:30:03.688715+08	\N	0	\N	2026-04-13 16:30:08.946677+08	AgACAgUAAxkBAAIIAmncqc3wn5q14Ke0_j5DhkzyWTiVAAKXDmsb13DhVg3NBO2FVymzAQADAgADeQADOwQ
44	140	56759	1	2026-04-13	2	COMPLETED	PASS	2026-04-13 16:30:03.688715+08	\N	0	\N	2026-04-13 16:30:07.818206+08	AgACAgUAAxkBAAIIBWncqeJZvZgx-TUTAsBW99xqPii6AAKqEWsbMCfoVr1MZRwNcTTxAQADAgADeQADOwQ
43	140	29337	1	2026-04-13	2	TIMEOUT	TIMEOUT	2026-04-13 16:30:03.688715+08	\N	0	\N	\N	\N
29	119	31088	1	2026-04-12	2	COMPLETED	PASS	2026-04-12 16:30:05.715106+08	\N	0	\N	2026-04-12 16:30:17.193226+08	AgACAgUAAxkBAAIHamnbWFfiLMjHv0piMuMbUE-JVIDzAAIgDWsbmfrZVinDmItNlWGuAQADAgADeQADOwQ
30	119	55516	1	2026-04-12	2	TIMEOUT	TIMEOUT	2026-04-12 16:30:05.715106+08	\N	0	\N	2026-04-12 16:30:18.019523+08	\N
46	141	58073	1	2026-04-13	3	COMPLETED	PASS	2026-04-13 18:30:04.57284+08	\N	0	\N	2026-04-13 18:30:08.33422+08	AgACAgUAAxkBAAIIDWncxdR4aG_td_T6guUTON5ELoXgAAKfDmsb_OXoVilEZiAIUIAaAQADAgADeQADOwQ
33	120	56773	1	2026-04-12	3	COMPLETED	PASS	2026-04-12 18:33:34.269846+08	\N	0	\N	2026-04-12 18:36:30.125049+08	AgACAgUAAxkBAAIHdWnbdgY1mcANZT0tGSVSv0WZDGZtAAIGD2sbqDnZVkHrL1dPaN2gAQADAgADeQADOwQ
32	120	56759	1	2026-04-12	3	COMPLETED	PASS	2026-04-12 18:33:34.269846+08	\N	0	\N	2026-04-12 18:36:29.356824+08	AgACAgUAAxkBAAIHeGnbdhX-u5IWIQMMbAWo1inWm9FrAAIJD2sbd_7YVuGaXEhUdG2qAQADAgADeQADOwQ
31	120	56753	1	2026-04-12	3	TIMEOUT	TIMEOUT	2026-04-12 18:33:34.269846+08	\N	0	\N	2026-04-12 18:36:28.599063+08	\N
47	141	59242	1	2026-04-13	3	COMPLETED	PASS	2026-04-13 18:30:04.57284+08	\N	0	\N	2026-04-13 18:30:09.170385+08	AgACAgUAAxkBAAIIEGncxeOMkRurv4oDvV-GhngWzHPYAALxDmsbCd7oVpcoR7M8wfNBAQADAgADeQADOwQ
48	141	72357	1	2026-04-13	3	COMPLETED	PASS	2026-04-13 18:30:04.57284+08	\N	0	\N	2026-04-13 18:30:09.899524+08	AgACAgUAAxkBAAIIE2ncxvvNpiTHZ-kWo9AGPhvaa1-BAALRD2sboozpVh5Rx4Myc3K5AQADAgADeQADOwQ
34	122	58073	1	2026-04-12	4	COMPLETED	PASS	2026-04-12 20:30:06.376007+08	\N	0	\N	2026-04-12 20:30:13.40622+08	AgACAgUAAxkBAAIHfWnbkH9-ETZQXTEgV722fGNxgke-AAKGDmsbINngVspt2rsnRUWdAQADAgADeQADOwQ
49	144	74114	1	2026-04-13	4	TIMEOUT	TIMEOUT	2026-04-13 20:30:05.986289+08	\N	0	\N	2026-04-13 20:30:10.089257+08	\N
50	144	74168	1	2026-04-13	4	TIMEOUT	TIMEOUT	2026-04-13 20:30:05.986289+08	\N	0	\N	\N	\N
36	122	72357	1	2026-04-12	4	COMPLETED	PASS	2026-04-12 20:30:06.376007+08	\N	0	\N	2026-04-12 20:37:04.741205+08	AgACAgUAAxkBAAIHh2nbkjELgGCVH0ZEvXsuTpcENHF9AAKLEWsb4UjYViwTfe1dR-52AQADAgADeQADOwQ
51	144	74306	1	2026-04-13	4	TIMEOUT	TIMEOUT	2026-04-13 20:30:05.986289+08	\N	0	\N	\N	\N
35	122	59242	1	2026-04-12	4	COMPLETED	PASS	2026-04-12 20:30:06.376007+08	\N	0	\N	2026-04-12 20:38:09.227005+08	AgACAgUAAxkBAAIHjGnbksIpeDRtNLdzx7PcwaI4y-nVAAKzDmsbtmfhVk05m-6ABAGfAQADAgADeQADOwQ
37	125	74114	1	2026-04-12	5	COMPLETED	PASS	2026-04-12 22:30:02.215643+08	\N	0	\N	2026-04-12 22:30:06.050428+08	AgACAgUAAxkBAAIHuWnbrTSXVKb7-ID9K9oB8dih4iTqAAKADWsb4nfgVhqxWk0_eyo7AQADAgADeQADOwQ
53	145	74322	1	2026-04-13	5	COMPLETED	PASS	2026-04-13 22:30:04.36208+08	\N	0	\N	2026-04-13 22:30:07.55739+08	AgACAgUAAxkBAAIIKWnc_iEh0_c3-Jm2Akg5Lf6w6obyAAIcD2sb8CvpVgmmoT-oSWkDAQADAgADeQADOwQ
54	145	4257	1	2026-04-13	5	COMPLETED	PASS	2026-04-13 22:30:04.36208+08	\N	0	\N	2026-04-13 22:30:08.829595+08	AgACAgUAAxkBAAIILWnc_mpKMYSh1jY_L0Lec9_aApWzAAIjDWsbk-3oVnejqT9lkeCYAQADAgADeQADOwQ
52	145	74314	1	2026-04-13	5	TIMEOUT	TIMEOUT	2026-04-13 22:30:04.36208+08	\N	0	\N	2026-04-13 22:30:06.761499+08	\N
40	139	4257	1	2026-04-13	1	COMPLETED	PASS	2026-04-13 14:30:02.723142+08	\N	0	\N	2026-04-13 14:31:11.806607+08	AgACAgUAAxkBAAIH8Gncjg70YvS9h-NBYzBw_QQZo8NnAAKgD2sbxvPoVho3xwpQxu0vAQADAgADeQADOwQ
42	139	17025	1	2026-04-13	1	CANCELLED	FAIL	2026-04-13 14:30:02.723142+08	\N	0	\N	2026-04-13 14:30:10.111521+08	\N
25	118	4257	1	2026-04-12	1	TIMEOUT	TIMEOUT	2026-04-12 14:30:05.357254+08	\N	0	\N	2026-04-13 14:31:07.79821+08	\N
26	118	16908	1	2026-04-12	1	COMPLETED	PASS	2026-04-12 14:30:05.357254+08	\N	0	\N	2026-04-13 14:38:07.886644+08	AgACAgUAAxkBAAIH-2nckqIXODtSfsV21A_e92_nCr84AAJaDWsb-rPhVqIRPT7iRD1GAQADAgADeQADOwQ
41	139	16908	1	2026-04-13	1	TIMEOUT	TIMEOUT	2026-04-13 14:30:02.723142+08	\N	0	\N	2026-04-13 14:38:02.11126+08	\N
28	119	29337	1	2026-04-12	2	TIMEOUT	TIMEOUT	2026-04-12 16:30:05.715106+08	\N	0	\N	\N	\N
38	125	74168	1	2026-04-12	5	TIMEOUT	TIMEOUT	2026-04-12 22:30:02.215643+08	\N	0	\N	\N	\N
39	125	74306	1	2026-04-12	5	TIMEOUT	TIMEOUT	2026-04-12 22:30:02.215643+08	\N	0	\N	\N	\N
\.


--
-- TOC entry 5284 (class 0 OID 17839)
-- Dependencies: 224
-- Data for Name: registrations; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.registrations (id, employee_id, tg_id, english_name, registered_at, registered_chat_id, tg_username, organization_id, shift_id) FROM stdin;
3	4257	7056750099	Karina	2026-03-16 06:58:14+08	7056750099	Y_UX_Karina	2	1
4	16908	6886314602	brick	2026-03-16 06:53:42+08	6886314602	Y_UX_Brick	2	1
7	31088	7510241572	aikantui	2026-03-16 06:53:24+08	7510241572	Y_UX_Aikantui	3	1
10	55516	7163866386	tanzaniju	2026-03-16 06:54:04+08	7163866386	Y_UX_Tanzaniju	2	1
12	56759	8157802833	Nlgelito	2026-03-16 06:53:05+08	8157802833	Y_UX_Nlgelito	3	1
15	59242	8178120332	Xitanua	2026-03-16 07:07:18+08	8178120332	Y_UX_Xitanua	2	1
19	74114	8580988163	Foxieya	2026-03-16 07:05:09+08	8580988163	Y_UX_Foxieya	2	1
20	74168	8590155218	Bekahs	2026-03-16 21:48:21+08	8590155218	Y_UX_Bekahs	3	1
5	17025	6562376911	Brucewillis	2026-03-16 01:49:47+08	6562376911	Y_UX_Brucewillis	1	1
6	29337	7736673658	Rapunzelli	2026-03-16 07:00:04+08	7736673658	Y_UX_Rapunzelli1	1	1
11	56753	7625966687	Kairice	2026-03-16 01:15:01+08	7625966687	Y_UX_Kairice	1	1
13	56773	7625201169	Singjang	2026-03-16 01:41:12+08	7625201169	Y_UX_Singjang	1	1
14	58073	7074207060	Padadgu	2026-03-16 01:54:57+08	7074207060	Y_UX_Padadgu	1	1
16	72357	8233548675	GRENADA	2026-03-16 06:56:29+08	8233548675	Y_UX_Grenada	2	1
21	74306	8532682955	NAYXUA	2026-03-17 22:01:10+08	8532682955	Y_UX_Nayxua	1	1
22	74314	8763615403	Kuroni	2026-03-17 21:30:53+08	8763615403	Y_UX_Kuroni	1	1
2	7122	6332760420	test	2026-04-03 21:14:40.948846+08	6332760420	jeffery1836	0	0
23	74322	8642653065	Yiliaza	2026-03-19 22:57:33+08	8642653065	Y_UX_Yiliaza	1	1
9	51964	7348045344	Sanchali	2026-03-19 23:24:49+08	7348045344	Sanverygoodli117	0	0
8	51761	7020886046	NOHHAEIL	2026-03-16 20:05:11+08	7020886046	Y_TC_NOHHAEIL	0	0
1	72494	8352461288	JINDIAO	2026-04-01 00:53:13.043669+08	8352461288	Y_UX_Jindiao	1	1
\.


--
-- TOC entry 5282 (class 0 OID 17829)
-- Dependencies: 222
-- Data for Name: shifts; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.shifts (id, checkin_time, checkout_time, timezone, is_overnight, attendance_group_id, qc_trigger_interval, qc_draw_count, qc_example_file_id, attendance_flex_interval, max_late_early_tolerance, qc_enabled) FROM stdin;
0	13:00:00	22:00:00	Asia/Bangkok	f	-1003767543777	01:00:00	3	AgACAgUAAxkBAAIBoGnbNMZjRh9p-hgQV41qnVbnVK4RAALPEGsbrFrZVp1LVFXg33aqAQADAgADeQADOwQ	03:00:00	03:00:00	f
1	13:00:00	22:00:00	Asia/Bangkok	f	-1003883297177	02:00:00	3	AgACAgUAAxkBAAIDImm9JwKJktpwWzQWii6hbCC440PHAAJbD2sbnmPoVRnSp36xaX_pAQADAgADeQADOgQ	03:00:00	03:00:00	f
\.


--
-- TOC entry 5290 (class 0 OID 17865)
-- Dependencies: 230
-- Data for Name: temporary_leave_applications; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.temporary_leave_applications (id, employee_id, organization_id, shift_id, start_at, end_at, leave_reason, remark, status, completed_at, created_at) FROM stdin;
7	7122	0	0	2026-04-11 20:00:00+08	2026-04-11 21:00:00+08	嫖娼	\N	EXPIRED	2026-04-11 23:10:55.264521+08	2026-04-11 19:59:26.844536+08
8	7122	0	0	2026-04-11 22:25:00+08	2026-04-11 22:30:00+08	嘿嘿	\N	COMPLETED	2026-04-11 23:10:55.264521+08	2026-04-11 22:25:30.148395+08
9	7122	0	0	2026-04-12 22:40:00+08	2026-04-12 22:50:00+08	出门吃饭	\N	COMPLETED	2026-04-12 22:50:02.79806+08	2026-04-12 22:40:34.447706+08
\.


--
-- TOC entry 5300 (class 0 OID 17915)
-- Dependencies: 240
-- Data for Name: temporary_qc_exemption_list; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.temporary_qc_exemption_list (id, shift_id, employee_id, source_effective_temporary_leave_id, updated_at, work_date, exemption_start_at, exemption_end_at) FROM stdin;
\.


--
-- TOC entry 5357 (class 0 OID 0)
-- Dependencies: 225
-- Name: admin_list_id_seq; Type: SEQUENCE SET; Schema: public; Owner: postgres
--

SELECT pg_catalog.setval('public.admin_list_id_seq', 2, true);


--
-- TOC entry 5358 (class 0 OID 0)
-- Dependencies: 247
-- Name: approval_task_queue_id_seq; Type: SEQUENCE SET; Schema: public; Owner: postgres
--

SELECT pg_catalog.setval('public.approval_task_queue_id_seq', 15, true);


--
-- TOC entry 5359 (class 0 OID 0)
-- Dependencies: 241
-- Name: audit_results_id_seq; Type: SEQUENCE SET; Schema: public; Owner: postgres
--

SELECT pg_catalog.setval('public.audit_results_id_seq', 277, true);


--
-- TOC entry 5360 (class 0 OID 0)
-- Dependencies: 249
-- Name: audit_task_queue_id_seq; Type: SEQUENCE SET; Schema: public; Owner: postgres
--

SELECT pg_catalog.setval('public.audit_task_queue_id_seq', 298, true);


--
-- TOC entry 5361 (class 0 OID 0)
-- Dependencies: 231
-- Name: clock_records_id_seq; Type: SEQUENCE SET; Schema: public; Owner: postgres
--

SELECT pg_catalog.setval('public.clock_records_id_seq', 229, true);


--
-- TOC entry 5362 (class 0 OID 0)
-- Dependencies: 233
-- Name: effective_leave_days_id_seq; Type: SEQUENCE SET; Schema: public; Owner: postgres
--

SELECT pg_catalog.setval('public.effective_leave_days_id_seq', 16, true);


--
-- TOC entry 5363 (class 0 OID 0)
-- Dependencies: 235
-- Name: effective_temporary_leaves_id_seq; Type: SEQUENCE SET; Schema: public; Owner: postgres
--

SELECT pg_catalog.setval('public.effective_temporary_leaves_id_seq', 2, true);


--
-- TOC entry 5364 (class 0 OID 0)
-- Dependencies: 245
-- Name: event_logs_id_seq; Type: SEQUENCE SET; Schema: public; Owner: postgres
--

SELECT pg_catalog.setval('public.event_logs_id_seq', 182, true);


--
-- TOC entry 5365 (class 0 OID 0)
-- Dependencies: 227
-- Name: leave_applications_id_seq; Type: SEQUENCE SET; Schema: public; Owner: postgres
--

SELECT pg_catalog.setval('public.leave_applications_id_seq', 6, true);


--
-- TOC entry 5366 (class 0 OID 0)
-- Dependencies: 253
-- Name: notification_queue_id_seq; Type: SEQUENCE SET; Schema: public; Owner: postgres
--

SELECT pg_catalog.setval('public.notification_queue_id_seq', 157, true);


--
-- TOC entry 5367 (class 0 OID 0)
-- Dependencies: 219
-- Name: organizations_id_seq; Type: SEQUENCE SET; Schema: public; Owner: postgres
--

SELECT pg_catalog.setval('public.organizations_id_seq', 1, true);


--
-- TOC entry 5368 (class 0 OID 0)
-- Dependencies: 237
-- Name: qc_exemption_fixed_list_id_seq; Type: SEQUENCE SET; Schema: public; Owner: postgres
--

SELECT pg_catalog.setval('public.qc_exemption_fixed_list_id_seq', 6, true);


--
-- TOC entry 5369 (class 0 OID 0)
-- Dependencies: 243
-- Name: qc_results_id_seq; Type: SEQUENCE SET; Schema: public; Owner: postgres
--

SELECT pg_catalog.setval('public.qc_results_id_seq', 48, true);


--
-- TOC entry 5370 (class 0 OID 0)
-- Dependencies: 251
-- Name: qc_task_queue_id_seq; Type: SEQUENCE SET; Schema: public; Owner: postgres
--

SELECT pg_catalog.setval('public.qc_task_queue_id_seq', 54, true);


--
-- TOC entry 5371 (class 0 OID 0)
-- Dependencies: 223
-- Name: registrations_id_seq; Type: SEQUENCE SET; Schema: public; Owner: postgres
--

SELECT pg_catalog.setval('public.registrations_id_seq', 24, true);


--
-- TOC entry 5372 (class 0 OID 0)
-- Dependencies: 221
-- Name: shifts_id_seq; Type: SEQUENCE SET; Schema: public; Owner: postgres
--

SELECT pg_catalog.setval('public.shifts_id_seq', 1, true);


--
-- TOC entry 5373 (class 0 OID 0)
-- Dependencies: 229
-- Name: temporary_leave_applications_id_seq; Type: SEQUENCE SET; Schema: public; Owner: postgres
--

SELECT pg_catalog.setval('public.temporary_leave_applications_id_seq', 9, true);


--
-- TOC entry 5374 (class 0 OID 0)
-- Dependencies: 239
-- Name: temporary_qc_exemption_list_id_seq; Type: SEQUENCE SET; Schema: public; Owner: postgres
--

SELECT pg_catalog.setval('public.temporary_qc_exemption_list_id_seq', 2, true);


--
-- TOC entry 4993 (class 2606 OID 17853)
-- Name: admin_list admin_list_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.admin_list
    ADD CONSTRAINT admin_list_pkey PRIMARY KEY (id);


--
-- TOC entry 5069 (class 2606 OID 17960)
-- Name: approval_task_queue approval_task_queue_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.approval_task_queue
    ADD CONSTRAINT approval_task_queue_pkey PRIMARY KEY (id);


--
-- TOC entry 5050 (class 2606 OID 17929)
-- Name: audit_results audit_results_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.audit_results
    ADD CONSTRAINT audit_results_pkey PRIMARY KEY (id);


--
-- TOC entry 5077 (class 2606 OID 17971)
-- Name: audit_task_queue audit_task_queue_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.audit_task_queue
    ADD CONSTRAINT audit_task_queue_pkey PRIMARY KEY (id);


--
-- TOC entry 5012 (class 2606 OID 17883)
-- Name: clock_records clock_records_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.clock_records
    ADD CONSTRAINT clock_records_pkey PRIMARY KEY (id);


--
-- TOC entry 5019 (class 2606 OID 17893)
-- Name: effective_leave_days effective_leave_days_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.effective_leave_days
    ADD CONSTRAINT effective_leave_days_pkey PRIMARY KEY (id);


--
-- TOC entry 5026 (class 2606 OID 17903)
-- Name: effective_temporary_leaves effective_temporary_leaves_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.effective_temporary_leaves
    ADD CONSTRAINT effective_temporary_leaves_pkey PRIMARY KEY (id);


--
-- TOC entry 5064 (class 2606 OID 17950)
-- Name: event_logs event_logs_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.event_logs
    ADD CONSTRAINT event_logs_pkey PRIMARY KEY (id);


--
-- TOC entry 5003 (class 2606 OID 17863)
-- Name: leave_applications leave_applications_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.leave_applications
    ADD CONSTRAINT leave_applications_pkey PRIMARY KEY (id);


--
-- TOC entry 5093 (class 2606 OID 17993)
-- Name: notification_queue notification_queue_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.notification_queue
    ADD CONSTRAINT notification_queue_pkey PRIMARY KEY (id);


--
-- TOC entry 4981 (class 2606 OID 17827)
-- Name: organizations organizations_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.organizations
    ADD CONSTRAINT organizations_pkey PRIMARY KEY (id);


--
-- TOC entry 5036 (class 2606 OID 17913)
-- Name: qc_exemption_fixed_list qc_exemption_fixed_list_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.qc_exemption_fixed_list
    ADD CONSTRAINT qc_exemption_fixed_list_pkey PRIMARY KEY (id);


--
-- TOC entry 5061 (class 2606 OID 17939)
-- Name: qc_results qc_results_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.qc_results
    ADD CONSTRAINT qc_results_pkey PRIMARY KEY (id);


--
-- TOC entry 5087 (class 2606 OID 17982)
-- Name: qc_task_queue qc_task_queue_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.qc_task_queue
    ADD CONSTRAINT qc_task_queue_pkey PRIMARY KEY (id);


--
-- TOC entry 4987 (class 2606 OID 17845)
-- Name: registrations registrations_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.registrations
    ADD CONSTRAINT registrations_pkey PRIMARY KEY (id);


--
-- TOC entry 4983 (class 2606 OID 17837)
-- Name: shifts shifts_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.shifts
    ADD CONSTRAINT shifts_pkey PRIMARY KEY (id);


--
-- TOC entry 5010 (class 2606 OID 17873)
-- Name: temporary_leave_applications temporary_leave_applications_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.temporary_leave_applications
    ADD CONSTRAINT temporary_leave_applications_pkey PRIMARY KEY (id);


--
-- TOC entry 5046 (class 2606 OID 17921)
-- Name: temporary_qc_exemption_list temporary_qc_exemption_list_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.temporary_qc_exemption_list
    ADD CONSTRAINT temporary_qc_exemption_list_pkey PRIMARY KEY (id);


--
-- TOC entry 4996 (class 2606 OID 18011)
-- Name: admin_list uq_admin_list_admin_employee_id; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.admin_list
    ADD CONSTRAINT uq_admin_list_admin_employee_id UNIQUE (admin_employee_id);


--
-- TOC entry 5075 (class 2606 OID 18198)
-- Name: approval_task_queue uq_approval_task_queue_app_level_approver; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.approval_task_queue
    ADD CONSTRAINT uq_approval_task_queue_app_level_approver UNIQUE (application_type, application_id, approval_level, approver_employee_id);


--
-- TOC entry 5082 (class 2606 OID 18216)
-- Name: audit_task_queue uq_audit_task_queue_log_employee_date_stage; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.audit_task_queue
    ADD CONSTRAINT uq_audit_task_queue_log_employee_date_stage UNIQUE (log_id, employee_id, target_date, audit_stage);


--
-- TOC entry 5024 (class 2606 OID 18076)
-- Name: effective_leave_days uq_effective_leave_days_employee_date_shift; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.effective_leave_days
    ADD CONSTRAINT uq_effective_leave_days_employee_date_shift UNIQUE (employee_id, leave_date, shift_id);


--
-- TOC entry 5032 (class 2606 OID 18096)
-- Name: effective_temporary_leaves uq_effective_temporary_leaves_employee_time_shift_app; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.effective_temporary_leaves
    ADD CONSTRAINT uq_effective_temporary_leaves_employee_time_shift_app UNIQUE (employee_id, leave_start_at, leave_end_at, shift_id, application_id);


--
-- TOC entry 5095 (class 2606 OID 18256)
-- Name: notification_queue uq_notification_queue_log_tg_template; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.notification_queue
    ADD CONSTRAINT uq_notification_queue_log_tg_template UNIQUE (log_id, notify_tg_id, template_id);


--
-- TOC entry 5038 (class 2606 OID 18117)
-- Name: qc_exemption_fixed_list uq_qc_exemption_fixed_list_shift_employee; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.qc_exemption_fixed_list
    ADD CONSTRAINT uq_qc_exemption_fixed_list_shift_employee UNIQUE (shift_id, employee_id);


--
-- TOC entry 5089 (class 2606 OID 18234)
-- Name: qc_task_queue uq_qc_task_queue_log_employee; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.qc_task_queue
    ADD CONSTRAINT uq_qc_task_queue_log_employee UNIQUE (log_id, employee_id);


--
-- TOC entry 4989 (class 2606 OID 17995)
-- Name: registrations uq_registrations_employee_id; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.registrations
    ADD CONSTRAINT uq_registrations_employee_id UNIQUE (employee_id);


--
-- TOC entry 4991 (class 2606 OID 17997)
-- Name: registrations uq_registrations_tg_id; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.registrations
    ADD CONSTRAINT uq_registrations_tg_id UNIQUE (tg_id);


--
-- TOC entry 5048 (class 2606 OID 18273)
-- Name: temporary_qc_exemption_list uq_temporary_qc_exemption_source; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.temporary_qc_exemption_list
    ADD CONSTRAINT uq_temporary_qc_exemption_source UNIQUE (source_effective_temporary_leave_id);


--
-- TOC entry 4994 (class 1259 OID 18017)
-- Name: idx_admin_list_admin_employee_id; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_admin_list_admin_employee_id ON public.admin_list USING btree (admin_employee_id);


--
-- TOC entry 5070 (class 1259 OID 18211)
-- Name: idx_approval_task_queue_applicant_employee_id; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_approval_task_queue_applicant_employee_id ON public.approval_task_queue USING btree (applicant_employee_id);


--
-- TOC entry 5071 (class 1259 OID 18212)
-- Name: idx_approval_task_queue_application_id; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_approval_task_queue_application_id ON public.approval_task_queue USING btree (application_id);


--
-- TOC entry 5072 (class 1259 OID 18213)
-- Name: idx_approval_task_queue_approver_employee_id; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_approval_task_queue_approver_employee_id ON public.approval_task_queue USING btree (approver_employee_id);


--
-- TOC entry 5073 (class 1259 OID 18214)
-- Name: idx_approval_task_queue_status_created_at; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_approval_task_queue_status_created_at ON public.approval_task_queue USING btree (task_status, task_created_at);


--
-- TOC entry 5051 (class 1259 OID 18167)
-- Name: idx_audit_results_employee_id; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_audit_results_employee_id ON public.audit_results USING btree (employee_id);


--
-- TOC entry 5052 (class 1259 OID 18168)
-- Name: idx_audit_results_org_date; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_audit_results_org_date ON public.audit_results USING btree (organization_id, audit_date);


--
-- TOC entry 5053 (class 1259 OID 18169)
-- Name: idx_audit_results_result; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_audit_results_result ON public.audit_results USING btree (result);


--
-- TOC entry 5054 (class 1259 OID 18170)
-- Name: idx_audit_results_shift_date; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_audit_results_shift_date ON public.audit_results USING btree (shift_id, audit_date);


--
-- TOC entry 5078 (class 1259 OID 18230)
-- Name: idx_audit_task_queue_employee_id; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_audit_task_queue_employee_id ON public.audit_task_queue USING btree (employee_id);


--
-- TOC entry 5079 (class 1259 OID 18231)
-- Name: idx_audit_task_queue_target_date; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_audit_task_queue_target_date ON public.audit_task_queue USING btree (target_date);


--
-- TOC entry 5080 (class 1259 OID 18232)
-- Name: idx_audit_task_queue_task_status_created_at; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_audit_task_queue_task_status_created_at ON public.audit_task_queue USING btree (task_status, created_at);


--
-- TOC entry 5013 (class 1259 OID 18070)
-- Name: idx_clock_records_clock_time; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_clock_records_clock_time ON public.clock_records USING btree (clock_time);


--
-- TOC entry 5014 (class 1259 OID 18071)
-- Name: idx_clock_records_employee_id; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_clock_records_employee_id ON public.clock_records USING btree (employee_id);


--
-- TOC entry 5015 (class 1259 OID 18072)
-- Name: idx_clock_records_employee_time; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_clock_records_employee_time ON public.clock_records USING btree (employee_id, clock_time);


--
-- TOC entry 5016 (class 1259 OID 18073)
-- Name: idx_clock_records_shift_id; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_clock_records_shift_id ON public.clock_records USING btree (shift_id);


--
-- TOC entry 5017 (class 1259 OID 18074)
-- Name: idx_clock_records_tg_id; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_clock_records_tg_id ON public.clock_records USING btree (tg_id);


--
-- TOC entry 5020 (class 1259 OID 18092)
-- Name: idx_effective_leave_days_employee_date; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_effective_leave_days_employee_date ON public.effective_leave_days USING btree (employee_id, leave_date);


--
-- TOC entry 5021 (class 1259 OID 18093)
-- Name: idx_effective_leave_days_employee_id; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_effective_leave_days_employee_id ON public.effective_leave_days USING btree (employee_id);


--
-- TOC entry 5022 (class 1259 OID 18094)
-- Name: idx_effective_leave_days_shift_id; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_effective_leave_days_shift_id ON public.effective_leave_days USING btree (shift_id);


--
-- TOC entry 5027 (class 1259 OID 18112)
-- Name: idx_effective_temporary_leaves_application_id; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_effective_temporary_leaves_application_id ON public.effective_temporary_leaves USING btree (application_id);


--
-- TOC entry 5028 (class 1259 OID 18113)
-- Name: idx_effective_temporary_leaves_employee_date; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_effective_temporary_leaves_employee_date ON public.effective_temporary_leaves USING btree (employee_id, effective_date);


--
-- TOC entry 5029 (class 1259 OID 18114)
-- Name: idx_effective_temporary_leaves_employee_id; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_effective_temporary_leaves_employee_id ON public.effective_temporary_leaves USING btree (employee_id);


--
-- TOC entry 5030 (class 1259 OID 18115)
-- Name: idx_effective_temporary_leaves_shift_id; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_effective_temporary_leaves_shift_id ON public.effective_temporary_leaves USING btree (shift_id);


--
-- TOC entry 5065 (class 1259 OID 18194)
-- Name: idx_event_logs_created_at; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_event_logs_created_at ON public.event_logs USING btree (created_at);


--
-- TOC entry 5066 (class 1259 OID 18195)
-- Name: idx_event_logs_event_result; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_event_logs_event_result ON public.event_logs USING btree (event_name, result);


--
-- TOC entry 5067 (class 1259 OID 18196)
-- Name: idx_event_logs_related_event; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_event_logs_related_event ON public.event_logs USING btree (related_event_name, related_event_id);


--
-- TOC entry 4997 (class 1259 OID 18034)
-- Name: idx_leave_applications_employee_id; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_leave_applications_employee_id ON public.leave_applications USING btree (employee_id);


--
-- TOC entry 4998 (class 1259 OID 18035)
-- Name: idx_leave_applications_organization_id; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_leave_applications_organization_id ON public.leave_applications USING btree (organization_id);


--
-- TOC entry 4999 (class 1259 OID 18036)
-- Name: idx_leave_applications_shift_id; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_leave_applications_shift_id ON public.leave_applications USING btree (shift_id);


--
-- TOC entry 5000 (class 1259 OID 18037)
-- Name: idx_leave_applications_start_end; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_leave_applications_start_end ON public.leave_applications USING btree (start_at, end_at);


--
-- TOC entry 5001 (class 1259 OID 18038)
-- Name: idx_leave_applications_status; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_leave_applications_status ON public.leave_applications USING btree (status);


--
-- TOC entry 5090 (class 1259 OID 18264)
-- Name: idx_notification_queue_notify_tg_id; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_notification_queue_notify_tg_id ON public.notification_queue USING btree (notify_tg_id);


--
-- TOC entry 5091 (class 1259 OID 18265)
-- Name: idx_notification_queue_task_status_created_at; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_notification_queue_task_status_created_at ON public.notification_queue USING btree (task_status, created_at);


--
-- TOC entry 5033 (class 1259 OID 18128)
-- Name: idx_qc_exemption_fixed_list_employee_id; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_qc_exemption_fixed_list_employee_id ON public.qc_exemption_fixed_list USING btree (employee_id);


--
-- TOC entry 5034 (class 1259 OID 18129)
-- Name: idx_qc_exemption_fixed_list_shift_id; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_qc_exemption_fixed_list_shift_id ON public.qc_exemption_fixed_list USING btree (shift_id);


--
-- TOC entry 5056 (class 1259 OID 18188)
-- Name: idx_qc_results_employee_id; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_qc_results_employee_id ON public.qc_results USING btree (employee_id);


--
-- TOC entry 5057 (class 1259 OID 18189)
-- Name: idx_qc_results_org_date; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_qc_results_org_date ON public.qc_results USING btree (organization_id, qc_date);


--
-- TOC entry 5058 (class 1259 OID 18190)
-- Name: idx_qc_results_result; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_qc_results_result ON public.qc_results USING btree (result);


--
-- TOC entry 5059 (class 1259 OID 18191)
-- Name: idx_qc_results_shift_date; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_qc_results_shift_date ON public.qc_results USING btree (shift_id, qc_date);


--
-- TOC entry 5083 (class 1259 OID 18252)
-- Name: idx_qc_task_queue_employee_id; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_qc_task_queue_employee_id ON public.qc_task_queue USING btree (employee_id);


--
-- TOC entry 5084 (class 1259 OID 18253)
-- Name: idx_qc_task_queue_shift_date_round; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_qc_task_queue_shift_date_round ON public.qc_task_queue USING btree (shift_id, qc_date, qc_round);


--
-- TOC entry 5085 (class 1259 OID 18254)
-- Name: idx_qc_task_queue_status_created_at; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_qc_task_queue_status_created_at ON public.qc_task_queue USING btree (status, created_at);


--
-- TOC entry 4984 (class 1259 OID 18008)
-- Name: idx_registrations_organization_id; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_registrations_organization_id ON public.registrations USING btree (organization_id);


--
-- TOC entry 4985 (class 1259 OID 18009)
-- Name: idx_registrations_shift_id; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_registrations_shift_id ON public.registrations USING btree (shift_id);


--
-- TOC entry 5004 (class 1259 OID 18055)
-- Name: idx_temporary_leave_applications_employee_id; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_temporary_leave_applications_employee_id ON public.temporary_leave_applications USING btree (employee_id);


--
-- TOC entry 5005 (class 1259 OID 18056)
-- Name: idx_temporary_leave_applications_organization_id; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_temporary_leave_applications_organization_id ON public.temporary_leave_applications USING btree (organization_id);


--
-- TOC entry 5006 (class 1259 OID 18057)
-- Name: idx_temporary_leave_applications_shift_id; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_temporary_leave_applications_shift_id ON public.temporary_leave_applications USING btree (shift_id);


--
-- TOC entry 5007 (class 1259 OID 18058)
-- Name: idx_temporary_leave_applications_start_end; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_temporary_leave_applications_start_end ON public.temporary_leave_applications USING btree (start_at, end_at);


--
-- TOC entry 5008 (class 1259 OID 18059)
-- Name: idx_temporary_leave_applications_status; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_temporary_leave_applications_status ON public.temporary_leave_applications USING btree (status);


--
-- TOC entry 5039 (class 1259 OID 18276)
-- Name: idx_temporary_qc_exemption_emp_window; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_temporary_qc_exemption_emp_window ON public.temporary_qc_exemption_list USING btree (employee_id, exemption_start_at, exemption_end_at);


--
-- TOC entry 5040 (class 1259 OID 18147)
-- Name: idx_temporary_qc_exemption_list_employee_id; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_temporary_qc_exemption_list_employee_id ON public.temporary_qc_exemption_list USING btree (employee_id);


--
-- TOC entry 5041 (class 1259 OID 18148)
-- Name: idx_temporary_qc_exemption_list_shift_id; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_temporary_qc_exemption_list_shift_id ON public.temporary_qc_exemption_list USING btree (shift_id);


--
-- TOC entry 5042 (class 1259 OID 18149)
-- Name: idx_temporary_qc_exemption_list_source_effective_leave_id; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_temporary_qc_exemption_list_source_effective_leave_id ON public.temporary_qc_exemption_list USING btree (source_effective_temporary_leave_id);


--
-- TOC entry 5043 (class 1259 OID 18275)
-- Name: idx_temporary_qc_exemption_shift_window; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_temporary_qc_exemption_shift_window ON public.temporary_qc_exemption_list USING btree (shift_id, exemption_start_at, exemption_end_at);


--
-- TOC entry 5044 (class 1259 OID 18274)
-- Name: idx_temporary_qc_exemption_shift_workdate_emp; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_temporary_qc_exemption_shift_workdate_emp ON public.temporary_qc_exemption_list USING btree (shift_id, work_date, employee_id);


--
-- TOC entry 5055 (class 1259 OID 18171)
-- Name: uq_audit_results_employee_date_stage_shift; Type: INDEX; Schema: public; Owner: postgres
--

CREATE UNIQUE INDEX uq_audit_results_employee_date_stage_shift ON public.audit_results USING btree (employee_id, audit_date, audit_stage, shift_id);


--
-- TOC entry 5062 (class 1259 OID 18192)
-- Name: uq_qc_results_employee_date_shift_round; Type: INDEX; Schema: public; Owner: postgres
--

CREATE UNIQUE INDEX uq_qc_results_employee_date_shift_round ON public.qc_results USING btree (employee_id, qc_date, shift_id, qc_round);


--
-- TOC entry 5098 (class 2606 OID 18012)
-- Name: admin_list fk_admin_list_admin_employee_id; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.admin_list
    ADD CONSTRAINT fk_admin_list_admin_employee_id FOREIGN KEY (admin_employee_id) REFERENCES public.registrations(employee_id) ON UPDATE CASCADE ON DELETE RESTRICT;


--
-- TOC entry 5124 (class 2606 OID 18199)
-- Name: approval_task_queue fk_approval_task_queue_applicant_employee_id; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.approval_task_queue
    ADD CONSTRAINT fk_approval_task_queue_applicant_employee_id FOREIGN KEY (applicant_employee_id) REFERENCES public.registrations(employee_id) ON UPDATE CASCADE ON DELETE RESTRICT;


--
-- TOC entry 5125 (class 2606 OID 18204)
-- Name: approval_task_queue fk_approval_task_queue_approver_employee_id; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.approval_task_queue
    ADD CONSTRAINT fk_approval_task_queue_approver_employee_id FOREIGN KEY (approver_employee_id) REFERENCES public.registrations(employee_id) ON UPDATE CASCADE ON DELETE RESTRICT;


--
-- TOC entry 5118 (class 2606 OID 18150)
-- Name: audit_results fk_audit_results_employee_id; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.audit_results
    ADD CONSTRAINT fk_audit_results_employee_id FOREIGN KEY (employee_id) REFERENCES public.registrations(employee_id) ON UPDATE CASCADE ON DELETE RESTRICT;


--
-- TOC entry 5119 (class 2606 OID 18155)
-- Name: audit_results fk_audit_results_organization_id; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.audit_results
    ADD CONSTRAINT fk_audit_results_organization_id FOREIGN KEY (organization_id) REFERENCES public.organizations(id) ON UPDATE CASCADE ON DELETE RESTRICT;


--
-- TOC entry 5120 (class 2606 OID 18160)
-- Name: audit_results fk_audit_results_shift_id; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.audit_results
    ADD CONSTRAINT fk_audit_results_shift_id FOREIGN KEY (shift_id) REFERENCES public.shifts(id) ON UPDATE CASCADE ON DELETE RESTRICT;


--
-- TOC entry 5126 (class 2606 OID 18217)
-- Name: audit_task_queue fk_audit_task_queue_employee_id; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.audit_task_queue
    ADD CONSTRAINT fk_audit_task_queue_employee_id FOREIGN KEY (employee_id) REFERENCES public.registrations(employee_id) ON UPDATE CASCADE ON DELETE RESTRICT;


--
-- TOC entry 5127 (class 2606 OID 18222)
-- Name: audit_task_queue fk_audit_task_queue_log_id; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.audit_task_queue
    ADD CONSTRAINT fk_audit_task_queue_log_id FOREIGN KEY (log_id) REFERENCES public.event_logs(id) ON UPDATE CASCADE ON DELETE RESTRICT;


--
-- TOC entry 5105 (class 2606 OID 18060)
-- Name: clock_records fk_clock_records_employee_id; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.clock_records
    ADD CONSTRAINT fk_clock_records_employee_id FOREIGN KEY (employee_id) REFERENCES public.registrations(employee_id) ON UPDATE CASCADE ON DELETE RESTRICT;


--
-- TOC entry 5106 (class 2606 OID 18065)
-- Name: clock_records fk_clock_records_shift_id; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.clock_records
    ADD CONSTRAINT fk_clock_records_shift_id FOREIGN KEY (shift_id) REFERENCES public.shifts(id) ON UPDATE CASCADE ON DELETE RESTRICT;


--
-- TOC entry 5107 (class 2606 OID 18077)
-- Name: effective_leave_days fk_effective_leave_days_application_id; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.effective_leave_days
    ADD CONSTRAINT fk_effective_leave_days_application_id FOREIGN KEY (application_id) REFERENCES public.leave_applications(id) ON UPDATE CASCADE ON DELETE RESTRICT;


--
-- TOC entry 5108 (class 2606 OID 18082)
-- Name: effective_leave_days fk_effective_leave_days_employee_id; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.effective_leave_days
    ADD CONSTRAINT fk_effective_leave_days_employee_id FOREIGN KEY (employee_id) REFERENCES public.registrations(employee_id) ON UPDATE CASCADE ON DELETE RESTRICT;


--
-- TOC entry 5109 (class 2606 OID 18087)
-- Name: effective_leave_days fk_effective_leave_days_shift_id; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.effective_leave_days
    ADD CONSTRAINT fk_effective_leave_days_shift_id FOREIGN KEY (shift_id) REFERENCES public.shifts(id) ON UPDATE CASCADE ON DELETE RESTRICT;


--
-- TOC entry 5110 (class 2606 OID 18097)
-- Name: effective_temporary_leaves fk_effective_temporary_leaves_application_id; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.effective_temporary_leaves
    ADD CONSTRAINT fk_effective_temporary_leaves_application_id FOREIGN KEY (application_id) REFERENCES public.temporary_leave_applications(id) ON UPDATE CASCADE ON DELETE RESTRICT;


--
-- TOC entry 5111 (class 2606 OID 18102)
-- Name: effective_temporary_leaves fk_effective_temporary_leaves_employee_id; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.effective_temporary_leaves
    ADD CONSTRAINT fk_effective_temporary_leaves_employee_id FOREIGN KEY (employee_id) REFERENCES public.registrations(employee_id) ON UPDATE CASCADE ON DELETE RESTRICT;


--
-- TOC entry 5112 (class 2606 OID 18107)
-- Name: effective_temporary_leaves fk_effective_temporary_leaves_shift_id; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.effective_temporary_leaves
    ADD CONSTRAINT fk_effective_temporary_leaves_shift_id FOREIGN KEY (shift_id) REFERENCES public.shifts(id) ON UPDATE CASCADE ON DELETE RESTRICT;


--
-- TOC entry 5099 (class 2606 OID 18018)
-- Name: leave_applications fk_leave_applications_employee_id; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.leave_applications
    ADD CONSTRAINT fk_leave_applications_employee_id FOREIGN KEY (employee_id) REFERENCES public.registrations(employee_id) ON UPDATE CASCADE ON DELETE RESTRICT;


--
-- TOC entry 5100 (class 2606 OID 18023)
-- Name: leave_applications fk_leave_applications_organization_id; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.leave_applications
    ADD CONSTRAINT fk_leave_applications_organization_id FOREIGN KEY (organization_id) REFERENCES public.organizations(id) ON UPDATE CASCADE ON DELETE RESTRICT;


--
-- TOC entry 5101 (class 2606 OID 18028)
-- Name: leave_applications fk_leave_applications_shift_id; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.leave_applications
    ADD CONSTRAINT fk_leave_applications_shift_id FOREIGN KEY (shift_id) REFERENCES public.shifts(id) ON UPDATE CASCADE ON DELETE RESTRICT;


--
-- TOC entry 5131 (class 2606 OID 18257)
-- Name: notification_queue fk_notification_queue_log_id; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.notification_queue
    ADD CONSTRAINT fk_notification_queue_log_id FOREIGN KEY (log_id) REFERENCES public.event_logs(id) ON UPDATE CASCADE ON DELETE RESTRICT;


--
-- TOC entry 5113 (class 2606 OID 18118)
-- Name: qc_exemption_fixed_list fk_qc_exemption_fixed_list_employee_id; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.qc_exemption_fixed_list
    ADD CONSTRAINT fk_qc_exemption_fixed_list_employee_id FOREIGN KEY (employee_id) REFERENCES public.registrations(employee_id) ON UPDATE CASCADE ON DELETE RESTRICT;


--
-- TOC entry 5114 (class 2606 OID 18123)
-- Name: qc_exemption_fixed_list fk_qc_exemption_fixed_list_shift_id; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.qc_exemption_fixed_list
    ADD CONSTRAINT fk_qc_exemption_fixed_list_shift_id FOREIGN KEY (shift_id) REFERENCES public.shifts(id) ON UPDATE CASCADE ON DELETE RESTRICT;


--
-- TOC entry 5121 (class 2606 OID 18172)
-- Name: qc_results fk_qc_results_employee_id; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.qc_results
    ADD CONSTRAINT fk_qc_results_employee_id FOREIGN KEY (employee_id) REFERENCES public.registrations(employee_id) ON UPDATE CASCADE ON DELETE RESTRICT;


--
-- TOC entry 5122 (class 2606 OID 18177)
-- Name: qc_results fk_qc_results_organization_id; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.qc_results
    ADD CONSTRAINT fk_qc_results_organization_id FOREIGN KEY (organization_id) REFERENCES public.organizations(id) ON UPDATE CASCADE ON DELETE RESTRICT;


--
-- TOC entry 5123 (class 2606 OID 18182)
-- Name: qc_results fk_qc_results_shift_id; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.qc_results
    ADD CONSTRAINT fk_qc_results_shift_id FOREIGN KEY (shift_id) REFERENCES public.shifts(id) ON UPDATE CASCADE ON DELETE RESTRICT;


--
-- TOC entry 5128 (class 2606 OID 18235)
-- Name: qc_task_queue fk_qc_task_queue_employee_id; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.qc_task_queue
    ADD CONSTRAINT fk_qc_task_queue_employee_id FOREIGN KEY (employee_id) REFERENCES public.registrations(employee_id) ON UPDATE CASCADE ON DELETE RESTRICT;


--
-- TOC entry 5129 (class 2606 OID 18245)
-- Name: qc_task_queue fk_qc_task_queue_log_id; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.qc_task_queue
    ADD CONSTRAINT fk_qc_task_queue_log_id FOREIGN KEY (log_id) REFERENCES public.event_logs(id) ON UPDATE CASCADE ON DELETE RESTRICT;


--
-- TOC entry 5130 (class 2606 OID 18240)
-- Name: qc_task_queue fk_qc_task_queue_shift_id; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.qc_task_queue
    ADD CONSTRAINT fk_qc_task_queue_shift_id FOREIGN KEY (shift_id) REFERENCES public.shifts(id) ON UPDATE CASCADE ON DELETE RESTRICT;


--
-- TOC entry 5096 (class 2606 OID 17998)
-- Name: registrations fk_registrations_organization_id; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.registrations
    ADD CONSTRAINT fk_registrations_organization_id FOREIGN KEY (organization_id) REFERENCES public.organizations(id) ON UPDATE CASCADE ON DELETE RESTRICT;


--
-- TOC entry 5097 (class 2606 OID 18003)
-- Name: registrations fk_registrations_shift_id; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.registrations
    ADD CONSTRAINT fk_registrations_shift_id FOREIGN KEY (shift_id) REFERENCES public.shifts(id) ON UPDATE CASCADE ON DELETE RESTRICT;


--
-- TOC entry 5102 (class 2606 OID 18039)
-- Name: temporary_leave_applications fk_temporary_leave_applications_employee_id; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.temporary_leave_applications
    ADD CONSTRAINT fk_temporary_leave_applications_employee_id FOREIGN KEY (employee_id) REFERENCES public.registrations(employee_id) ON UPDATE CASCADE ON DELETE RESTRICT;


--
-- TOC entry 5103 (class 2606 OID 18044)
-- Name: temporary_leave_applications fk_temporary_leave_applications_organization_id; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.temporary_leave_applications
    ADD CONSTRAINT fk_temporary_leave_applications_organization_id FOREIGN KEY (organization_id) REFERENCES public.organizations(id) ON UPDATE CASCADE ON DELETE RESTRICT;


--
-- TOC entry 5104 (class 2606 OID 18049)
-- Name: temporary_leave_applications fk_temporary_leave_applications_shift_id; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.temporary_leave_applications
    ADD CONSTRAINT fk_temporary_leave_applications_shift_id FOREIGN KEY (shift_id) REFERENCES public.shifts(id) ON UPDATE CASCADE ON DELETE RESTRICT;


--
-- TOC entry 5115 (class 2606 OID 18132)
-- Name: temporary_qc_exemption_list fk_temporary_qc_exemption_list_employee_id; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.temporary_qc_exemption_list
    ADD CONSTRAINT fk_temporary_qc_exemption_list_employee_id FOREIGN KEY (employee_id) REFERENCES public.registrations(employee_id) ON UPDATE CASCADE ON DELETE RESTRICT;


--
-- TOC entry 5116 (class 2606 OID 18137)
-- Name: temporary_qc_exemption_list fk_temporary_qc_exemption_list_shift_id; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.temporary_qc_exemption_list
    ADD CONSTRAINT fk_temporary_qc_exemption_list_shift_id FOREIGN KEY (shift_id) REFERENCES public.shifts(id) ON UPDATE CASCADE ON DELETE RESTRICT;


--
-- TOC entry 5117 (class 2606 OID 18142)
-- Name: temporary_qc_exemption_list fk_temporary_qc_exemption_list_source_effective_leave_id; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.temporary_qc_exemption_list
    ADD CONSTRAINT fk_temporary_qc_exemption_list_source_effective_leave_id FOREIGN KEY (source_effective_temporary_leave_id) REFERENCES public.effective_temporary_leaves(id) ON UPDATE CASCADE ON DELETE RESTRICT;


--
-- TOC entry 5320 (class 0 OID 0)
-- Dependencies: 5
-- Name: SCHEMA public; Type: ACL; Schema: -; Owner: pg_database_owner
--

REVOKE USAGE ON SCHEMA public FROM PUBLIC;


-- Completed on 2026-05-07 15:52:42

--
-- PostgreSQL database dump complete
--

\unrestrict WwjWiC5LGUfJI7HAU1I0ezkDAiRkHF4TXbxKim8uS53iCDeMaBg8bXKlybTqty9

