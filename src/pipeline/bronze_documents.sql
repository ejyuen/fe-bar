-- Bronze: raw contract binaries picked up incrementally from the UC Volume with Auto Loader.
-- doc_id = sha256(path). Auto Loader checkpoints guarantee each file is ingested once.
CREATE OR REFRESH STREAMING TABLE ${catalog}.raw.bronze_documents (
  CONSTRAINT has_content EXPECT (content IS NOT NULL AND size > 0) ON VIOLATION DROP ROW
)
COMMENT 'Raw CUAD v1 contract PDFs (CC BY 4.0) ingested from /Volumes/<catalog>/raw/contracts/pdfs'
AS SELECT
  sha2(path, 256)     AS doc_id,
  path,
  content,
  length              AS size,
  current_timestamp() AS ingested_at
FROM STREAM read_files('${volume_path}', format => 'binaryFile');
