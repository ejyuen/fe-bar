-- Silver: ai_parse_document (schema version 2.0) over each PDF, once per document (streaming).
-- full_text = all non-header/footer/figure element content in reading order.
CREATE OR REFRESH STREAMING TABLE silver_parsed (
  CONSTRAINT parse_ok        EXPECT (parse_status = 'ok')      ON VIOLATION DROP ROW,
  CONSTRAINT text_min_length EXPECT (length(full_text) > 200)  ON VIOLATION DROP ROW
)
COMMENT 'Parsed contracts (ai_parse_document v2.0). full_text is tagged pii.'
AS
WITH parsed AS (
  SELECT doc_id, path,
         ai_parse_document(content, map('version', '2.0', 'descriptionElementTypes', '')) AS parsed
  FROM STREAM(${catalog}.raw.bronze_documents)
),
elems AS (
  SELECT doc_id, path, parsed,
         from_json(to_json(parsed:document.elements), 'array<struct<type:string,content:string>>') AS elements,
         from_json(to_json(parsed:document.pages), 'array<struct<id:int>>')                        AS pages,
         from_json(to_json(parsed:error_status), 'array<struct<error_message:string,page_id:int>>') AS errors
  FROM parsed
),
txt AS (
  SELECT doc_id, path, parsed, pages, errors,
         array_join(transform(filter(elements, e -> e.type NOT IN ('page_header', 'page_footer', 'page_number', 'figure')),
                              e -> e.content), '\n') AS full_text
  FROM elems
)
SELECT
  doc_id,
  path,
  parsed,
  full_text,
  coalesce(size(pages), 0) AS page_count,
  CASE WHEN parsed IS NULL OR full_text IS NULL OR length(full_text) = 0 THEN 'error' ELSE 'ok' END AS parse_status,
  CASE WHEN size(errors) > 0 THEN to_json(errors) END AS parse_error,
  current_timestamp() AS parsed_at
FROM txt;
