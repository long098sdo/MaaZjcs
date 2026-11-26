using System;
using System.Diagnostics;
using System.IO;
using System.Reflection;
using System.Text.RegularExpressions;
using System.Threading;

// .NET startup hook for the existing MFA title button. Compiled separately from MFA.
public static class StartupHook
{
    public static void Initialize()
    {
        new Thread(CheckForUpdate) { IsBackground = true }.Start();
    }

    private static void CheckForUpdate()
    {
        try
        {
            var directory = AppDomain.CurrentDomain.BaseDirectory;
            string latest;
            using (var check = Process.Start(PythonCommand(directory, false, "--query")))
            {
                if (check == null || !check.WaitForExit(30000))
                    return;
                latest = check.StandardOutput.ReadToEnd().Trim();
                if (check.ExitCode != 0 || !Regex.IsMatch(latest, @"\Av?\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?\z"))
                    return;
            }

            for (var attempt = 0; attempt < 120; attempt++)
            {
                foreach (var assembly in AppDomain.CurrentDomain.GetAssemblies())
                {
                    var instances = assembly.GetType("MFAAvalonia.Helper.Instances");
                    var model = instances == null ? null : GetReadyModel(instances, assembly);
                    if (model == null)
                        continue;

                    var dispatcher = assembly.GetType("MFAAvalonia.Helper.DispatcherHelper");
                    var post = dispatcher == null ? null : dispatcher.GetMethod("PostOnMainThread");
                    var title = model.GetType().GetProperty("WindowUpdateInfo");
                    var action = model.GetType().GetProperty("TempResourceUpdateAction");
                    if (post == null || title == null || action == null)
                        return;

                    Action show = () =>
                    {
                        action.SetValue(model, (Action)(() =>
                        {
                            try { Process.Start(PythonCommand(directory, true, "--show-release " + latest)); }
                            catch (Exception error) { Trace.WriteLine(error); }
                        }), null);
                        title.SetValue(model, "检测到新版本：" + latest, null);
                    };
                    post.Invoke(null, new object[] { show, Activator.CreateInstance(post.GetParameters()[1].ParameterType) });
                    return;
                }
                Thread.Sleep(250);
            }
        }
        catch (Exception error)
        {
            Trace.WriteLine(error);
        }
    }

    private static object GetReadyModel(Type instances, Assembly assembly)
    {
        var lookup = instances.GetMethod("TryGetResolved", BindingFlags.Static | BindingFlags.Public);
        var modelType = assembly.GetType("MFAAvalonia.ViewModels.Windows.RootViewModel");
        if (lookup != null && modelType != null)
        {
            var arguments = new object[] { null };
            lookup.MakeGenericMethod(modelType).Invoke(null, arguments);
            return arguments[0];
        }

        var field = instances.GetField("_rootViewModel", BindingFlags.Static | BindingFlags.NonPublic);
        return field == null ? null : field.GetValue(null);
    }

    private static ProcessStartInfo PythonCommand(string directory, bool dialog, string arguments)
    {
        var name = dialog ? "pythonw.exe" : "python.exe";
        var bundled = Path.Combine(directory, "portable", "python", name);
        return new ProcessStartInfo
        {
            FileName = File.Exists(bundled) ? bundled : name,
            Arguments = "\"" + Path.Combine(directory, "tools", "check_update.py") + "\" " + arguments,
            WorkingDirectory = directory,
            UseShellExecute = false,
            CreateNoWindow = true,
            RedirectStandardOutput = !dialog,
        };
    }
}
