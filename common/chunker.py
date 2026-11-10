
import re
from typing import Any, Callable, Dict, List, Optional, Tuple
from .models import Block, HeadingBlock, TableBlock, Document

def count_tokens_heuristic(text: str) -> int:

    if not text:
        return 0
    words = text.split()
    return max(1, int(len(words) * 1.33))

def chunk_document(
    doc: Document,
    target_tokens: int = 700,
    overlap_tokens: int = 100,
    custom_tokenizer: Optional[Callable[[str], int]] = None,
) -> List[Dict[str, Any]]:

    token_counter = custom_tokenizer or count_tokens_heuristic

    if not doc.blocks:
        return []

    chunks: List[Dict[str, Any]] = []

    block_records: List[Dict[str, Any]] = []

    heading_stack: List[Tuple[int, str]] = []

    for idx, block in enumerate(doc.blocks):
        if isinstance(block, HeadingBlock):

            while heading_stack and heading_stack[-1][0] >= block.level:
                heading_stack.pop()
            heading_stack.append((block.level, block.text))
            path = [h[1] for h in heading_stack]
            block_text = f"{'#' * block.level} {block.text}"
        elif isinstance(block, TableBlock):
            tbl_lines = []
            if block.caption:
                tbl_lines.append(f"Table: {block.caption}")
            if block.headers:
                tbl_lines.append(" | ".join(block.headers))
            for row in block.rows:
                tbl_lines.append(" | ".join(row))
            block_text = "\n".join(tbl_lines)
            path = [h[1] for h in heading_stack]
        else:
            block_text = getattr(block, "text", "") or getattr(block, "code", "") or getattr(block, "latex", "") or ""
            path = [h[1] for h in heading_stack]

        tokens = token_counter(block_text)
        block_records.append({
            "index": idx,
            "text": block_text,
            "tokens": tokens,
            "path": list(path),
        })

    curr_chunk_blocks: List[Dict[str, Any]] = []
    curr_tokens = 0
    chunk_index = 1

    i = 0
    while i < len(block_records):
        rec = block_records[i]

        if rec["tokens"] >= target_tokens:
            if curr_chunk_blocks:

                chunk_text = "\n\n".join(b["text"] for b in curr_chunk_blocks if b["text"].strip())
                chunks.append({
                    "chunk_id": f"chunk_{chunk_index:04d}",
                    "heading_path": curr_chunk_blocks[0]["path"] if curr_chunk_blocks else [],
                    "text": chunk_text,
                    "token_count": token_counter(chunk_text),
                    "start_block": curr_chunk_blocks[0]["index"],
                    "end_block": curr_chunk_blocks[-1]["index"],
                })
                chunk_index += 1
                curr_chunk_blocks = []
                curr_tokens = 0

            chunks.append({
                "chunk_id": f"chunk_{chunk_index:04d}",
                "heading_path": rec["path"],
                "text": rec["text"],
                "token_count": rec["tokens"],
                "start_block": rec["index"],
                "end_block": rec["index"],
            })
            chunk_index += 1
            i += 1
            continue

        if curr_tokens + rec["tokens"] > target_tokens and curr_chunk_blocks:

            chunk_text = "\n\n".join(b["text"] for b in curr_chunk_blocks if b["text"].strip())
            chunks.append({
                "chunk_id": f"chunk_{chunk_index:04d}",
                "heading_path": curr_chunk_blocks[0]["path"] if curr_chunk_blocks else [],
                "text": chunk_text,
                "token_count": token_counter(chunk_text),
                "start_block": curr_chunk_blocks[0]["index"],
                "end_block": curr_chunk_blocks[-1]["index"],
            })
            chunk_index += 1

            overlap_acc = 0
            overlap_blocks = []
            for b in reversed(curr_chunk_blocks):
                if overlap_acc + b["tokens"] <= overlap_tokens:
                    overlap_blocks.insert(0, b)
                    overlap_acc += b["tokens"]
                else:
                    break

            curr_chunk_blocks = list(overlap_blocks)
            curr_tokens = overlap_acc

        curr_chunk_blocks.append(rec)
        curr_tokens += rec["tokens"]
        i += 1

    if curr_chunk_blocks:
        chunk_text = "\n\n".join(b["text"] for b in curr_chunk_blocks if b["text"].strip())
        chunks.append({
            "chunk_id": f"chunk_{chunk_index:04d}",
            "heading_path": curr_chunk_blocks[0]["path"] if curr_chunk_blocks else [],
            "text": chunk_text,
            "token_count": token_counter(chunk_text),
            "start_block": curr_chunk_blocks[0]["index"],
            "end_block": curr_chunk_blocks[-1]["index"],
        })

    return chunks
