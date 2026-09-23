import * as vscode from 'vscode';
import { Finding, ReviewResult, runCli, toDiagnostic } from './cli';

/**
 * The diagnostic collection that holds all codereview findings.
 * One collection per workspace keeps the Problems panel grouped.
 */
let collection: vscode.DiagnosticCollection;

/**
 * Debounce timer so rapid saves don't spawn overlapping CLI processes.
 */
let debounce: NodeJS.Timeout | undefined;

/**
 * Activate the extension: register the diagnostic collection, the
 * on-save review, and the manual review/clear commands.
 */
export function activate(context: vscode.ExtensionContext): void {
  collection = vscode.languages.createDiagnosticCollection('codereview');
  context.subscriptions.push(collection);

  // Review the active file when it is saved (static only by default).
  context.subscriptions.push(
    vscode.workspace.onDidSaveTextDocument((doc) => {
      if (doc.languageId !== 'python') {
        return;
      }
      const config = vscode.workspace.getConfiguration('codereview');
      if (!config.get<boolean>('reviewOnSave', true)) {
        return;
      }
      scheduleReview(doc.uri);
    })
  );

  // Manual review of the active file (respects the llmOnSave setting).
  context.subscriptions.push(
    vscode.commands.registerCommand('codereview.reviewFile', () => {
      const editor = vscode.window.activeTextEditor;
      if (!editor || editor.document.languageId !== 'python') {
        vscode.window.showInformationMessage(
          'Open a Python file to review it.'
        );
        return;
      }
      const config = vscode.workspace.getConfiguration('codereview');
      const llm = config.get<boolean>('llmOnSave', false);
      void review(editor.document.uri, llm);
    })
  );

  // Clear all findings.
  context.subscriptions.push(
    vscode.commands.registerCommand('codereview.clearFindings', () => {
      collection.clear();
    })
  );
}

/**
 * Debounce a review of the given document by 500ms.
 */
function scheduleReview(uri: vscode.Uri): void {
  if (debounce) {
    clearTimeout(debounce);
  }
  debounce = setTimeout(() => {
    void review(uri, false);
  }, 500);
}

/**
 * Run the codereview CLI against a document and publish the findings
 * as diagnostics. Errors (missing CLI, syntax error) surface as a
 * notification instead of crashing the extension.
 */
async function review(uri: vscode.Uri, llm: boolean): Promise<void> {
  const config = vscode.workspace.getConfiguration('codereview');
  const cliPath = config.get<string>('cliPath', 'codereview');

  try {
    const result = await runCli(uri.fsPath, cliPath, llm);
    collection.set(uri, result.issues.map(toDiagnostic));
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    vscode.window.showWarningMessage(
      `codereview: ${message}. Install the CLI with 'pip install codereview'.`
    );
  }
}

export function deactivate(): void {
  if (debounce) {
    clearTimeout(debounce);
  }
}