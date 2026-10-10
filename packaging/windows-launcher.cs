using System;
using System.Diagnostics;
using System.IO;
using System.Windows.Forms;
using System.Collections.Generic;
using System.Threading;
using System.Web.Script.Serialization;

[assembly: System.Reflection.AssemblyTitle("Spool")]
[assembly: System.Reflection.AssemblyProduct("Spool")]
[assembly: System.Reflection.AssemblyDescription("Spool desktop launcher")]

internal static class SpoolLauncher
{
    private static void Log(string name, int? child, Exception error, int? exitCode = null)
    {
        // Separate, bounded early-launch journal: Python may not have started.
        // No arguments, paths, exception messages or account data are retained.
        try
        {
            string data = Environment.GetEnvironmentVariable("VIDEO_DOWNLOADER_DATA_DIR");
            if (String.IsNullOrEmpty(data))
                data = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "VideoDownloader");
            string folder = Path.Combine(data, "logs");
            Directory.CreateDirectory(folder);
            using (Mutex gate = new Mutex(false, "Local\\Spool.Launcher.Diagnostics"))
            {
                bool acquired = false;
                try { acquired = gate.WaitOne(200); }
                catch (AbandonedMutexException) { acquired = true; }
                if (!acquired) return;
                try
                {
                    string file = Path.Combine(folder, "launcher.jsonl");
                    string previous = Path.Combine(folder, "launcher.previous.jsonl");
                    if (File.Exists(file) && new FileInfo(file).Length > 262144)
                    {
                        if (File.Exists(previous)) File.Delete(previous);
                        File.Move(file, previous);
                    }
                    var row = new Dictionary<string, object> {
                        {"time", DateTime.UtcNow.ToString("o")}, {"component", "launcher"},
                        {"event", name}, {"pid", Process.GetCurrentProcess().Id}, {"child_pid", child},
                        {"exit_code", exitCode},
                        {"version", System.Reflection.Assembly.GetExecutingAssembly().GetName().Version.ToString()},
                        {"error_type", error == null ? null : error.GetType().Name}
                    };
                    var nativeError = error as System.ComponentModel.Win32Exception;
                    if (nativeError != null) row["native_error_code"] = nativeError.NativeErrorCode;
                    File.AppendAllText(file, new JavaScriptSerializer().Serialize(row) + Environment.NewLine);
                }
                finally { gate.ReleaseMutex(); }
            }
        }
        catch { /* Diagnostic failure must not prevent the app from opening. */ }
    }

    [STAThread]
    private static void Main()
    {
        try
        {
            Log("launcher.starting", null, null);
            string folder = AppDomain.CurrentDomain.BaseDirectory;
            string engine = Path.Combine(folder, "VideoDownloader.exe");
            if (!File.Exists(engine))
                throw new FileNotFoundException("Keep Spool.exe beside VideoDownloader.exe and its _internal folder.");
            Process child = Process.Start(new ProcessStartInfo(engine) {
                WorkingDirectory = folder,
                UseShellExecute = false,
                CreateNoWindow = true
            });
            Log("launcher.started", child.Id, null);
            if (child.WaitForExit(1500) && child.ExitCode != 0)
                Log("launcher.child_exited", child.Id, null, child.ExitCode);
        }
        catch (Exception error)
        {
            Log("launcher.failed", null, error);
            MessageBox.Show(error.Message, "Spool", MessageBoxButtons.OK, MessageBoxIcon.Error);
        }
    }
}
