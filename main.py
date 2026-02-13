"""
File Parser & Summary Generator (MCP Local) - Background Processing
====================================================================
FastAPI application untuk parsing dan generate ringkasan dari berbagai jenis file
dengan background processing dan job ID tracking.

Mendukung file types:
- .sql → ekstrak struktur table & query utama
- .json → baca seluruh struktur, cari field utama
- .txt → baca sebagai teks, cari pola baris penting
- .csv → baca header & baris pertama, hitung jumlah baris, cek kolom utama

Dependencies:
- pip install fastapi uvicorn python-multipart pandas

Usage:
- uvicorn main:app --reload --host 0.0.0.0 --port 8001
"""

import os
import re
import tempfile
import shutil
import uuid
import asyncio
from typing import Dict, Any, List, Optional
from pathlib import Path
from datetime import datetime
from enum import Enum
from contextlib import asynccontextmanager
import json

import uvicorn
from fastapi import FastAPI, File, UploadFile, HTTPException, BackgroundTasks
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

try:
    import pandas as pd
except ImportError:
    raise ImportError("pandas tidak terinstall. Jalankan: pip install pandas")


# ============================================================================
# MODELS
# ============================================================================

class JobStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class JobResponse(BaseModel):
    job_id: str
    status: str
    message: str


class JobDetail(BaseModel):
    job_id: str
    status: JobStatus
    file_type: str | None = None
    filename: str | None = None
    file_size_kb: float | None = None
    created_at: str
    started_at: str | None = None
    completed_at: str | None = None
    error: str | None = None
    result: Dict[str, Any] | None = None
    progress: Dict[str, Any] | None = None


# ============================================================================
# JOB STORAGE (In-Memory)
# ============================================================================

class JobStorage:
    """In-memory storage untuk job management."""

    def __init__(self):
        self.jobs: Dict[str, Dict[str, Any]] = {}
        self.lock = asyncio.Lock()

    async def create_job(
        self,
        filename: str,
        file_type: str,
        file_size_kb: float
    ) -> str:
        """Buat job baru dan return job_id."""
        job_id = str(uuid.uuid4())

        async with self.lock:
            self.jobs[job_id] = {
                "job_id": job_id,
                "status": JobStatus.PENDING,
                "file_type": file_type,
                "filename": filename,
                "file_size_kb": file_size_kb,
                "created_at": datetime.now().isoformat(),
                "started_at": None,
                "completed_at": None,
                "error": None,
                "result": None,
                "progress": {
                    "stage": "pending",
                    "message": "Menunggu diproses..."
                }
            }

        return job_id

    async def update_job(
        self,
        job_id: str,
        **kwargs
    ) -> bool:
        """Update job data."""
        async with self.lock:
            if job_id not in self.jobs:
                return False

            for key, value in kwargs.items():
                self.jobs[job_id][key] = value

        return True

    async def update_progress(
        self,
        job_id: str,
        stage: str,
        message: str
    ) -> bool:
        """Update job progress."""
        async with self.lock:
            if job_id not in self.jobs:
                return False

            self.jobs[job_id]["progress"] = {
                "stage": stage,
                "message": message
            }

        return True

    async def get_job(self, job_id: str) -> Dict[str, Any] | None:
        """Get job data by ID."""
        async with self.lock:
            return self.jobs.get(job_id)

    async def get_all_jobs(self) -> Dict[str, Dict[str, Any]]:
        """Get all jobs."""
        async with self.lock:
            return self.jobs.copy()


# Global job storage instance
job_storage = JobStorage()


# ============================================================================
# KONFIGURASI APLIKASI
# ============================================================================

app = FastAPI(
    title="File Parser & Summary Generator",
    description="Parse dan generate ringkasan dari berbagai jenis file dengan background processing",
    version="2.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

MAX_FILE_SIZE = 5 * 1024 * 1024

SUPPORTED_TYPES = ['sql', 'json', 'txt', 'csv']


# ============================================================================
# PARSER FUNCTIONS
# ============================================================================

# SQL Parser patterns
SQL_PATTERNS = {
    "create_table": re.compile(r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?[`']?(\w+)[`']?", re.IGNORECASE),
    "alter_table": re.compile(r"ALTER\s+TABLE\s+[`']?(\w+)[`']?", re.IGNORECASE),
    "drop_table": re.compile(r"DROP\s+TABLE\s+(?:IF\s+EXISTS\s+)?[`']?(\w+)[`']?", re.IGNORECASE),
    "insert_into": re.compile(r"INSERT\s+INTO\s+[`']?(\w+)[`']?", re.IGNORECASE),
    "update_table": re.compile(r"UPDATE\s+[`']?(\w+)[`']?", re.IGNORECASE),
    "delete_from": re.compile(r"DELETE\s+FROM\s+[`']?(\w+)[`']?", re.IGNORECASE),
    "select_from": re.compile(r"SELECT\s+.+?\s+FROM\s+[`']?(\w+)[`']?", re.IGNORECASE),
}

# TXT Parser keywords
IMPORTANT_KEYWORDS = [
    "error", "success", "failed", "warning", "total",
    "exception", "critical", "completed", "started", "finished"
]


def parse_sql_file(content: str) -> Dict[str, Any]:
    """Parse file SQL dan ekstrak struktur table & query utama."""
    lines = content.split('\n')
    tables_found = set()
    queries_count = 0
    query_types = {"CREATE": 0, "ALTER": 0, "DROP": 0, "INSERT": 0, "UPDATE": 0, "DELETE": 0, "SELECT": 0}

    for line in lines:
        line = line.strip()
        if not line or line.startswith('--') or line.startswith('/*'):
            continue

        line_upper = line.upper()

        for pattern_name, pattern in SQL_PATTERNS.items():
            matches = pattern.findall(line)
            for match in matches:
                tables_found.add(match)

        for qtype in query_types.keys():
            if qtype in line_upper:
                query_types[qtype] += 1
                queries_count += 1
                break

    return {
        "tables_found": list(tables_found),
        "tables_count": len(tables_found),
        "total_queries": queries_count,
        "query_types": query_types,
        "has_transaction": "BEGIN" in content.upper() or "START TRANSACTION" in content.upper(),
        "has_index": "INDEX" in content.upper()
    }


def parse_json_file(content: str) -> Dict[str, Any]:
    """Parse file JSON dan ekstrak informasi utama."""
    try:
        data = json.loads(content)

        key_fields = []
        record_count = 0
        structure_type = "unknown"

        if isinstance(data, list):
            record_count = len(data)
            structure_type = "array"

            if record_count > 0:
                first_item = data[0]
                if isinstance(first_item, dict):
                    key_fields = list(first_item.keys())[:10]

        elif isinstance(data, dict):
            structure_type = "object"
            key_fields = list(data.keys())[:10]

            if all(isinstance(v, dict) for v in data.values()):
                record_count = len(data)
            elif isinstance(data.get("data"), list):
                record_count = len(data.get("data", []))

        return {
            "structure_type": structure_type,
            "key_fields": key_fields,
            "record_count": record_count,
            "has_nested_data": "nested" in str(data).lower()
        }

    except json.JSONDecodeError as e:
        return {
            "error": f"Invalid JSON: {str(e)}",
            "structure_type": "invalid"
        }


def parse_txt_file(content: str) -> Dict[str, Any]:
    """Parse file TXT dan cari pola baris penting."""
    lines = content.split('\n')

    total_lines = len(lines)
    non_empty_lines = sum(1 for line in lines if line.strip())

    keyword_counts = {kw: 0 for kw in IMPORTANT_KEYWORDS}
    important_lines = []

    for i, line in enumerate(lines, 1):
        line_lower = line.lower()

        for keyword in IMPORTANT_KEYWORDS:
            if keyword in line_lower:
                keyword_counts[keyword] += 1

                if keyword in ["error", "failed", "exception", "critical"]:
                    important_lines.append({
                        "line_number": i,
                        "type": keyword,
                        "content": line.strip()[:100]
                    })

                if len(important_lines) >= 20:
                    break

        if len(important_lines) >= 20:
            break

    detected_type = "unknown"
    if keyword_counts["error"] > 0 or keyword_counts["exception"] > 0:
        detected_type = "log_file"
    elif keyword_counts["success"] > 0:
        detected_type = "process_log"
    elif non_empty_lines < 50:
        detected_type = "short_text"
    else:
        detected_type = "document"

    return {
        "detected_type": detected_type,
        "total_lines": total_lines,
        "non_empty_lines": non_empty_lines,
        "keyword_counts": keyword_counts,
        "important_lines": important_lines[:10],
        "total_chars": len(content)
    }


def parse_csv_file(file_path: str, filename: str) -> Dict[str, Any]:
    """Parse file CSV dan ekstrak informasi utama."""
    try:
        df = pd.read_csv(file_path, nrows=1000)
        rows_count = len(df)

        if rows_count == 1000:
            with open(file_path, 'r') as f:
                total_lines = sum(1 for _ in f) - 1
                rows_count = total_lines

        columns = df.columns.tolist()
        main_columns = columns[:10]

        column_types = {}
        for col in columns:
            dtype = str(df[col].dtype)
            column_types[col] = dtype

        null_counts = df.isnull().sum().to_dict()

        return {
            "rows": rows_count,
            "columns": len(columns),
            "main_columns": main_columns,
            "all_columns": columns,
            "column_types": column_types,
            "null_counts": {k: v for k, v in null_counts.items() if v > 0},
            "sample_first_rows": df.head(3).to_dict(orient="records")
        }

    except pd.errors.EmptyDataError:
        return {"error": "File CSV kosong"}
    except pd.errors.ParserError as e:
        return {"error": f"Error parsing CSV: {str(e)}"}
    except Exception as e:
        return {"error": f"Error: {str(e)}"}


def generate_summary(
    filename: str,
    file_type: str,
    size_kb: float,
    parsed_data: Dict[str, Any]
) -> str:
    """Generate ringkasan singkat (max 500 karakter)."""
    summary_parts = [f"File {file_type.upper()} '{filename}' ({size_kb:.1f} KB)."]

    if file_type == "sql":
        tables = parsed_data.get("tables_count", 0)
        queries = parsed_data.get("total_queries", 0)
        summary_parts.append(
            f"Berisi {queries} query SQL dengan {tables} tabel. " +
            ("Terdapat transaksi database." if parsed_data.get("has_transaction") else "")
        )

    elif file_type == "json":
        struct = parsed_data.get("structure_type", "unknown")
        records = parsed_data.get("record_count", 0)
        fields = parsed_data.get("key_fields", [])
        summary_parts.append(
            f"Struktur data berupa {struct}. Berisi {records} record. " +
            f"Field utama: {', '.join(fields[:5])}."
        )

    elif file_type == "txt":
        dtype = parsed_data.get("detected_type", "unknown")
        lines = parsed_data.get("non_empty_lines", 0)
        kw_counts = parsed_data.get("keyword_counts", {})

        keywords_found = [f"{k}({v})" for k, v in kw_counts.items() if v > 0]
        summary_parts.append(
            f"Terdeteksi sebagai {dtype}. Berisi {lines} baris teks. " +
            (f"Kata kunci: {', '.join(keywords_found)}." if keywords_found else "")
        )

    elif file_type == "csv":
        rows = parsed_data.get("rows", 0)
        cols = parsed_data.get("columns", 0)
        main_cols = parsed_data.get("main_columns", [])

        if isinstance(rows, int):
            summary_parts.append(
                f"Berisi {rows:,} baris data dengan {cols} kolom. " +
                f"Kolom utama: {', '.join(main_cols[:5])}."
            )
        else:
            summary_parts.append("Data CSV dengan struktur tabular.")

    return " ".join(summary_parts)[:500]


# ============================================================================
# BACKGROUND PROCESSING FUNCTION
# ============================================================================

async def process_file_job(
    job_id: str,
    file_path: str,
    file_type: str,
    filename: str,
    file_size_kb: float
):
    """Background task untuk memproses file."""
    try:
        # Update status ke processing
        await job_storage.update_job(
            job_id,
            status=JobStatus.PROCESSING,
            started_at=datetime.now().isoformat()
        )

        # Update progress
        await job_storage.update_progress(
            job_id,
            "reading",
            f"Membaca file {file_type.upper()}..."
        )

        # Baca konten file
        with open(file_path, 'rb') as f:
            content_bytes = f.read()

        content_str = content_bytes.decode('utf-8', errors='ignore')

        # Update progress
        await job_storage.update_progress(
            job_id,
            "parsing",
            f"MemParsing file {file_type.upper()}..."
        )

        # Parse berdasarkan tipe file
        loop = asyncio.get_event_loop()

        if file_type == 'sql':
            parsed_data = await loop.run_in_executor(None, parse_sql_file, content_str)

        elif file_type == 'json':
            parsed_data = await loop.run_in_executor(None, parse_json_file, content_str)

        elif file_type == 'txt':
            parsed_data = await loop.run_in_executor(None, parse_txt_file, content_str)

        elif file_type == 'csv':
            parsed_data = await loop.run_in_executor(None, parse_csv_file, file_path, filename)

        else:
            parsed_data = {"error": "Unsupported file type"}

        # Update progress
        await job_storage.update_progress(
            job_id,
            "generating_summary",
            "Membuat ringkasan..."
        )

        # Generate ringkasan
        summary = generate_summary(
            filename=filename,
            file_type=file_type,
            size_kb=file_size_kb,
            parsed_data=parsed_data
        )

        # Result
        result = {
            "filename": filename,
            "file_type": file_type,
            "size_kb": file_size_kb,
            "summary": summary,
            "key_info": parsed_data
        }

        # Update job dengan hasil
        await job_storage.update_job(
            job_id,
            status=JobStatus.COMPLETED,
            completed_at=datetime.now().isoformat(),
            result=result,
            progress={
                "stage": "completed",
                "message": "Proses selesai!"
            }
        )

    except Exception as e:
        # Update job dengan error
        await job_storage.update_job(
            job_id,
            status=JobStatus.FAILED,
            completed_at=datetime.now().isoformat(),
            error=str(e),
            progress={
                "stage": "failed",
                "message": f"Error: {str(e)}"
            }
        )


# ============================================================================
# API ENDPOINTS
# ============================================================================

@app.get("/")
async def root():
    """Root endpoint dengan informasi API."""
    return {
        "service": "File Parser & Summary Generator - Background Processing",
        "version": "2.0.0",
        "endpoints": {
            "POST /parse-file": "Upload file untuk diproses di background",
            "GET /jobs/{job_id}": "Cek status job berdasarkan ID",
            "GET /jobs": "List semua job",
            "DELETE /jobs/{job_id}": "Hapus job dari memory",
            "GET /health": "Cek status layanan"
        }
    }


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    jobs = await job_storage.get_all_jobs()

    return {
        "status": "healthy",
        "version": "2.0.0",
        "active_jobs": sum(1 for j in jobs.values() if j["status"] in [JobStatus.PENDING, JobStatus.PROCESSING])
    }


@app.post("/parse-file", response_model=JobResponse)
async def parse_file(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...)
):
    """
    Upload file untuk diproses di background.

    Returns job_id untuk tracking status proses.
    """
    # Ekstrak ekstensi file
    filename = file.filename or "unknown"
    file_ext = Path(filename).suffix.lower().lstrip('.')

    # Validasi tipe file
    if file_ext not in SUPPORTED_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Tipe file tidak didukung. Gunakan: {', '.join(SUPPORTED_TYPES)}"
        )

    # Baca konten file
    content_bytes = await file.read()

    # Validasi ukuran file
    if len(content_bytes) > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=400,
            detail=f"Ukuran file terlalu besar. Maksimum {MAX_FILE_SIZE // (1024*1024)}MB"
        )

    if len(content_bytes) == 0:
        raise HTTPException(
            status_code=400,
            detail="File kosong"
        )

    # Buat job
    job_id = await job_storage.create_job(
        filename=filename,
        file_type=file_ext,
        file_size_kb=len(content_bytes) / 1024
    )

    # Simpan file ke temporary
    temp_dir = tempfile.mkdtemp()
    temp_file_path = os.path.join(temp_dir, f"{job_id}.{file_ext}")

    try:
        with open(temp_file_path, 'wb') as f:
            f.write(content_bytes)

        # Simpan path temp di job untuk cleanup nanti
        await job_storage.update_job(job_id, _temp_path=temp_dir, _temp_file=temp_file_path)

        # Tambahkan background task
        background_tasks.add_task(
            process_file_job,
            job_id,
            temp_file_path,
            file_ext,
            filename,
            len(content_bytes) / 1024
        )

        return JobResponse(
            job_id=job_id,
            status=JobStatus.PENDING,
            message=f"File '{filename}' diterima. Sedang diproses."
        )

    except Exception as e:
        # Cleanup on error
        if os.path.exists(temp_file_path):
            os.remove(temp_file_path)
        if os.path.exists(temp_dir):
            shutil.rmtree(temp_dir)

        raise HTTPException(
            status_code=500,
            detail=f"Error saat inisialisasi job: {str(e)}"
        )


@app.get("/jobs/{job_id}", response_model=JobDetail)
async def get_job_status(job_id: str):
    """
    Cek status job berdasarkan ID.

    Returns detail job beserta progress dan hasil (jika completed).
    """
    job = await job_storage.get_job(job_id)

    if not job:
        raise HTTPException(
            status_code=404,
            detail=f"Job dengan ID '{job_id}' tidak ditemukan"
        )

    # Remove internal fields
    job.pop("_temp_path", None)
    job.pop("_temp_file", None)

    return JobDetail(**job)


@app.get("/jobs")
async def list_all_jobs():
    """List semua job yang pernah dibuat."""
    jobs = await job_storage.get_all_jobs()

    # Remove internal fields
    result = []
    for job_id, job_data in jobs.items():
        job_data_copy = job_data.copy()
        job_data_copy.pop("_temp_path", None)
        job_data_copy.pop("_temp_file", None)

        # Sembunyikan result untuk list view (too large)
        if job_data["status"] == JobStatus.COMPLETED and job_data.get("result"):
            result_preview = job_data["result"].copy()
            if "key_info" in result_preview and len(result_preview["key_info"]) > 100:
                result_preview["key_info"] = f"[{str(type(result_preview['key_info']))} - data too large]"
            job_data_copy["result_preview"] = result_preview
            job_data_copy.pop("result", None)

        result.append(job_data_copy)

    return {
        "total_jobs": len(result),
        "jobs": result
    }


@app.delete("/jobs/{job_id}")
async def delete_job(job_id: str):
    """
    Hapus job dari memory dan cleanup temporary files.
    """
    job = await job_storage.get_job(job_id)

    if not job:
        raise HTTPException(
            status_code=404,
            detail=f"Job dengan ID '{job_id}' tidak ditemukan"
        )

    # Cleanup temporary files
    temp_path = job.get("_temp_path")
    temp_file = job.get("_temp_file")

    if temp_file and os.path.exists(temp_file):
        os.remove(temp_file)
    if temp_path and os.path.exists(temp_path):
        shutil.rmtree(temp_path)

    # Remove from storage
    async with job_storage.lock:
        if job_id in job_storage.jobs:
            del job_storage.jobs[job_id]

    return {
        "message": f"Job '{job_id}' berhasil dihapus",
        "job_id": job_id
    }


if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8001,
        reload=True
    )
