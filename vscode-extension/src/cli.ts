import * as vscode from 'vscode';
import { execFile } from 'child_process';

/**
 * A single finding from the codereview CLI's --json output.
 * Mirrors the Python `Issue` dataclass fields.
 */
export interface Finding {
  code: string;
  severity: string; // "INFO" | "SUGGESTION" | "WARNING"
  line: number;     // 1-based
  message: string;
  category?: string;
}

/**
 * The parsed --json output for one file.
 */
export interface ReviewResult {
  path: string;
  issues: Finding[];
}

/**
 * Run the codereview CLI against a file and parse its --json output.
 *
 * Spawns `codereview --json <file>` as a subprocess (no server, no daemon).
 * Returns the parsed findings, or throws with a user-friendly message if
 * the CLI is missing or fails.
 */
export async function runCli(
  filePath: string,
  cliPath: string,
  llm: boolean
): Promise<ReviewResult> {
  const args = ['--json'];
  if (llm) {
    args.push('--llm');
  }
  args.push(filePath);

  const cwd = vscode.workspace.getWorkspaceFolder(vscode.Uri.file(filePath))?.uri.fsPath;
  const { stdout, stderr, code } = await new Promise<{
    stdout: string;
    stderr: string;
    code: number;
  }>((resolve, reject) => {
    execFile(
      cliPath,
      args,
      {
        cwd,
        env: { ...process.env, PYTHONIOENCODING: 'utf-8' },
      },
      (error, out, err) => {
        if (error) {
          reject(new Error(error.message));
          return;
        }
        resolve({ stdout: out, stderr: err, code: 0 });
      }
    );
  });

  if (code !== 0) {
    const detail = stderr.trim().split('\n').pop() ?? '';
    throw new Error(
      `codereview exited with code ${code}${detail ? `: ${detail}` : ''}`
    );
  }

  // The CLI prints one pretty-printed JSON object per file. For a single
  // file there is exactly one object; parse the whole stdout.
  const text = stdout.trim();
  if (!text) {
    return { path: filePath, issues: [] };
  }
  const data = JSON.parse(text) as ReviewResult;
  return data;
}

/**
 * Map a CLI severity string to a VS Code DiagnosticSeverity.
 */
export function toDiagnosticSeverity(severity: string): vscode.DiagnosticSeverity {
  switch (severity) {
    case 'WARNING':
      return vscode.DiagnosticSeverity.Warning;
    case 'INFO':
      return vscode.DiagnosticSeverity.Information;
    case 'SUGGESTION':
    default:
      return vscode.DiagnosticSeverity.Hint;
  }
}

/**
 * Convert a Finding to a VS Code Diagnostic.
 *
 * The CLI reports 1-based line numbers; VS Code ranges are 0-based and
 * span the whole line (we don't know the exact column from the CLI).
 */
export function toDiagnostic(finding: Finding): vscode.Diagnostic {
  const line = Math.max(0, finding.line - 1);
  const range = new vscode.Range(line, 0, line, 1000);
  const diagnostic = new vscode.Diagnostic(
    range,
    finding.message,
    toDiagnosticSeverity(finding.severity)
  );
  diagnostic.code = finding.code;
  diagnostic.source = 'codereview';
  return diagnostic;
}