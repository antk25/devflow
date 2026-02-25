#!/bin/bash
# RAG Knowledge Base Auto-Reindex Check
# Runs at SessionStart to detect changed/new/deleted files in the knowledge base.
# Outputs structured instructions for Claude to process via mcp-local-rag tools.

RAG_DIR="$HOME/projects/rag-knowledge"
STATE_FILE="$RAG_DIR/.rag-index-state"
LOCK_FILE="$RAG_DIR/.rag-reindex.lock"

# Avoid concurrent runs
if [ -f "$LOCK_FILE" ]; then
    lock_age=$(( $(date +%s) - $(stat -c %Y "$LOCK_FILE" 2>/dev/null || echo 0) ))
    if [ "$lock_age" -lt 300 ]; then
        exit 0
    fi
    rm -f "$LOCK_FILE"
fi
touch "$LOCK_FILE"
trap 'rm -f "$LOCK_FILE"' EXIT

# Check if RAG directory exists
if [ ! -d "$RAG_DIR" ]; then
    exit 0
fi

# Collect current files (only indexable types, skip hidden dirs and state files)
current_files=$(find "$RAG_DIR" -type f \( -name "*.md" -o -name "*.txt" -o -name "*.pdf" -o -name "*.docx" \) \
    ! -path "*/.lancedb/*" ! -path "*/.models/*" ! -path "*/.git/*" \
    ! -name ".rag-index-state" ! -name ".rag-reindex.lock" \
    2>/dev/null | sort)

# Load previous state (format: "mtime filepath" per line)
declare -A prev_state
if [ -f "$STATE_FILE" ]; then
    while IFS='|' read -r mtime filepath; do
        prev_state["$filepath"]="$mtime"
    done < "$STATE_FILE"
fi

# Detect changes
new_files=()
changed_files=()
deleted_files=()
new_state=""

while IFS= read -r filepath; do
    [ -z "$filepath" ] && continue
    mtime=$(stat -c %Y "$filepath" 2>/dev/null)
    [ -z "$mtime" ] && continue

    new_state+="${mtime}|${filepath}"$'\n'

    if [ -z "${prev_state[$filepath]+x}" ]; then
        new_files+=("$filepath")
    elif [ "${prev_state[$filepath]}" != "$mtime" ]; then
        changed_files+=("$filepath")
    fi

    # Remove from prev_state to detect deletions
    unset "prev_state[$filepath]"
done <<< "$current_files"

# Remaining entries in prev_state are deleted files
for filepath in "${!prev_state[@]}"; do
    deleted_files+=("$filepath")
done

# Save new state
echo -n "$new_state" > "$STATE_FILE"

# Calculate totals
total_changes=$(( ${#new_files[@]} + ${#changed_files[@]} + ${#deleted_files[@]} ))

# Output only if there are changes
if [ "$total_changes" -eq 0 ]; then
    exit 0
fi

# Output structured report
echo "RAG_REINDEX_NEEDED"
echo "==================="
echo "Changes detected in RAG knowledge base ($total_changes files):"
echo ""

if [ ${#new_files[@]} -gt 0 ]; then
    echo "NEW (${#new_files[@]} files - need ingest):"
    for f in "${new_files[@]}"; do
        echo "  + $f"
    done
    echo ""
fi

if [ ${#changed_files[@]} -gt 0 ]; then
    echo "CHANGED (${#changed_files[@]} files - need re-ingest):"
    for f in "${changed_files[@]}"; do
        echo "  ~ $f"
    done
    echo ""
fi

if [ ${#deleted_files[@]} -gt 0 ]; then
    echo "DELETED (${#deleted_files[@]} files - need removal from index):"
    for f in "${deleted_files[@]}"; do
        echo "  - $f"
    done
    echo ""
fi

echo "ACTION: Process the above changes using mcp__local-rag tools."
echo "  - NEW/CHANGED: use mcp__local-rag__ingest_file for each file"
echo "  - DELETED: use mcp__local-rag__delete_file for each file"
