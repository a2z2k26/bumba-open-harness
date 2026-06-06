/**
 * Sandbox File Operation Tools
 * Adapted from agent-sandboxes file management tools
 *
 * Provides 10 file operations:
 * - files_list: List directory contents
 * - files_read: Read text file
 * - files_write: Write text file
 * - files_upload: Upload binary file
 * - files_download: Download binary file
 * - file_exists: Check file existence
 * - file_info: Get file metadata
 * - file_remove: Delete file
 * - file_rename: Rename/move file
 * - make_directory: Create directory
 */

import { getSandbox } from './sandbox-lifecycle.js';

// ============================================================================
// files_list - List directory contents
// ============================================================================

export interface FilesListArgs {
  sandboxId: string;
  path?: string;
}

export interface FilesListResult {
  path: string;
  entries: FileEntry[];
  count: number;
}

export interface FileEntry {
  name: string;
  path: string;
  type: 'file' | 'directory';
  size?: number;
}

/**
 * List files and directories in a sandbox path
 */
export async function filesList(args: FilesListArgs): Promise<FilesListResult> {
  const { sandboxId, path: dirPath = '/' } = args;

  const sandbox = getSandbox(sandboxId);
  if (!sandbox) {
    throw new Error(`Sandbox ${sandboxId} not found`);
  }

  // List directory contents
  const entries = await sandbox.files.list(dirPath);

  const fileEntries: FileEntry[] = entries.map((entry) => ({
    name: entry.name,
    path: entry.path,
    type: entry.type as 'file' | 'directory',
    size: entry.size,
  }));

  return {
    path: dirPath,
    entries: fileEntries,
    count: fileEntries.length,
  };
}

// ============================================================================
// files_read - Read text file
// ============================================================================

export interface FilesReadArgs {
  sandboxId: string;
  path: string;
}

export interface FilesReadResult {
  path: string;
  content: string;
  size: number;
}

/**
 * Read a text file from sandbox
 */
export async function filesRead(args: FilesReadArgs): Promise<FilesReadResult> {
  const { sandboxId, path } = args;

  const sandbox = getSandbox(sandboxId);
  if (!sandbox) {
    throw new Error(`Sandbox ${sandboxId} not found`);
  }

  // Read file content
  const content = await sandbox.files.read(path);

  return {
    path,
    content,
    size: content.length,
  };
}

// ============================================================================
// files_write - Write text file
// ============================================================================

export interface FilesWriteArgs {
  sandboxId: string;
  path: string;
  content: string;
}

export interface FilesWriteResult {
  path: string;
  size: number;
  success: boolean;
}

/**
 * Write a text file to sandbox
 */
export async function filesWrite(args: FilesWriteArgs): Promise<FilesWriteResult> {
  const { sandboxId, path, content } = args;

  const sandbox = getSandbox(sandboxId);
  if (!sandbox) {
    throw new Error(`Sandbox ${sandboxId} not found`);
  }

  // Write file
  await sandbox.files.write(path, content);

  return {
    path,
    size: content.length,
    success: true,
  };
}

// ============================================================================
// files_upload - Upload binary file
// ============================================================================

export interface FilesUploadArgs {
  sandboxId: string;
  path: string;
  content: string; // Base64 encoded binary data
}

export interface FilesUploadResult {
  path: string;
  size: number;
  success: boolean;
}

/**
 * Upload a binary file to sandbox
 */
export async function filesUpload(args: FilesUploadArgs): Promise<FilesUploadResult> {
  const { sandboxId, path, content } = args;

  const sandbox = getSandbox(sandboxId);
  if (!sandbox) {
    throw new Error(`Sandbox ${sandboxId} not found`);
  }

  // Decode base64 content
  const buffer = Buffer.from(content, 'base64');

  // Write binary file (convert Buffer to ArrayBuffer)
  await sandbox.files.write(path, buffer.buffer.slice(buffer.byteOffset, buffer.byteOffset + buffer.byteLength));

  return {
    path,
    size: buffer.length,
    success: true,
  };
}

// ============================================================================
// files_download - Download binary file
// ============================================================================

export interface FilesDownloadArgs {
  sandboxId: string;
  path: string;
}

export interface FilesDownloadResult {
  path: string;
  content: string; // Base64 encoded binary data
  size: number;
}

/**
 * Download a binary file from sandbox
 */
export async function filesDownload(args: FilesDownloadArgs): Promise<FilesDownloadResult> {
  const { sandboxId, path } = args;

  const sandbox = getSandbox(sandboxId);
  if (!sandbox) {
    throw new Error(`Sandbox ${sandboxId} not found`);
  }

  // Read binary file as buffer
  const contentBytes = await sandbox.files.read(path, { format: 'bytes' });
  const buffer = Buffer.from(contentBytes);

  // Encode as base64
  const content = buffer.toString('base64');

  return {
    path,
    content,
    size: buffer.length,
  };
}

// ============================================================================
// file_exists - Check file existence
// ============================================================================

export interface FileExistsArgs {
  sandboxId: string;
  path: string;
}

export interface FileExistsResult {
  path: string;
  exists: boolean;
}

/**
 * Check if a file or directory exists
 */
export async function fileExists(args: FileExistsArgs): Promise<FileExistsResult> {
  const { sandboxId, path } = args;

  const sandbox = getSandbox(sandboxId);
  if (!sandbox) {
    throw new Error(`Sandbox ${sandboxId} not found`);
  }

  try {
    // Try to read the file - if it succeeds, file exists
    await sandbox.files.read(path);
    return {
      path,
      exists: true,
    };
  } catch (error) {
    // If read fails, file doesn't exist
    return {
      path,
      exists: false,
    };
  }
}

// ============================================================================
// file_info - Get file metadata
// ============================================================================

export interface FileInfoArgs {
  sandboxId: string;
  path: string;
}

export interface FileInfoResult {
  path: string;
  exists: boolean;
  type?: 'file' | 'directory';
  size?: number;
  mode?: number;
}

/**
 * Get file or directory metadata
 */
export async function fileInfo(args: FileInfoArgs): Promise<FileInfoResult> {
  const { sandboxId, path } = args;

  const sandbox = getSandbox(sandboxId);
  if (!sandbox) {
    throw new Error(`Sandbox ${sandboxId} not found`);
  }

  try {
    // Try to read as file first
    const content = await sandbox.files.read(path);

    return {
      path,
      exists: true,
      type: 'file',
      size: content.length,
    };
  } catch (error) {
    // If read fails, might be a directory or doesn't exist
    try {
      await sandbox.files.list(path);
      return {
        path,
        exists: true,
        type: 'directory',
      };
    } catch {
      return {
        path,
        exists: false,
      };
    }
  }
}

// ============================================================================
// file_remove - Delete file
// ============================================================================

export interface FileRemoveArgs {
  sandboxId: string;
  path: string;
}

export interface FileRemoveResult {
  path: string;
  removed: boolean;
  message: string;
}

/**
 * Remove a file or directory
 */
export async function fileRemove(args: FileRemoveArgs): Promise<FileRemoveResult> {
  const { sandboxId, path } = args;

  const sandbox = getSandbox(sandboxId);
  if (!sandbox) {
    throw new Error(`Sandbox ${sandboxId} not found`);
  }

  // Remove file
  await sandbox.files.remove(path);

  return {
    path,
    removed: true,
    message: 'File removed successfully',
  };
}

// ============================================================================
// file_rename - Rename/move file
// ============================================================================

export interface FileRenameArgs {
  sandboxId: string;
  oldPath: string;
  newPath: string;
}

export interface FileRenameResult {
  oldPath: string;
  newPath: string;
  renamed: boolean;
  message: string;
}

/**
 * Rename or move a file
 */
export async function fileRename(args: FileRenameArgs): Promise<FileRenameResult> {
  const { sandboxId, oldPath, newPath } = args;

  const sandbox = getSandbox(sandboxId);
  if (!sandbox) {
    throw new Error(`Sandbox ${sandboxId} not found`);
  }

  // Read file content
  const content = await sandbox.files.read(oldPath);

  // Write to new location
  await sandbox.files.write(newPath, content);

  // Remove old file
  await sandbox.files.remove(oldPath);

  return {
    oldPath,
    newPath,
    renamed: true,
    message: 'File renamed successfully',
  };
}

// ============================================================================
// make_directory - Create directory
// ============================================================================

export interface MakeDirectoryArgs {
  sandboxId: string;
  path: string;
}

export interface MakeDirectoryResult {
  path: string;
  created: boolean;
  message: string;
}

/**
 * Create a directory (and parent directories if needed)
 */
export async function makeDirectory(args: MakeDirectoryArgs): Promise<MakeDirectoryResult> {
  const { sandboxId, path } = args;

  const sandbox = getSandbox(sandboxId);
  if (!sandbox) {
    throw new Error(`Sandbox ${sandboxId} not found`);
  }

  // Create directory using mkdir -p
  await sandbox.commands.run(`mkdir -p "${path}"`);

  return {
    path,
    created: true,
    message: 'Directory created successfully',
  };
}
