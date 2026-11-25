// Guard the directory from which the launcher can later elevate its worker.
using System;
using System.Collections.Generic;
using System.IO;
using System.Runtime.InteropServices;
using System.Security.AccessControl;
using System.Security.Principal;
using System.Text;
using System.Text.RegularExpressions;
using Microsoft.Win32.SafeHandles;

internal static class SetupLocation
{
    private const string Administrators = "S-1-5-32-544";
    private const string SystemAccount = "S-1-5-18";
    private const string TrustedInstaller = "S-1-5-80-956008885-3418522649-1831038044-1853292631-2271478464";
    private const string CreatorOwner = "S-1-3-0";
    private const int DeleteChild = 0x40;
    private const int AclWrite = 0x40000 | 0x80000 | 0x10000000 | 0x40000000;
    private const int DirectoryWrite = 0x2 | 0x4 | 0x10 | 0x100 | 0x10000;

    private static int Main(string[] args)
    {
        int limit;
        if (args.Length != 2 || (args[0] != "check" && args[0] != "prepare") ||
            !Int32.TryParse(args[1], out limit))
            return 10;
        try
        {
            string path = Environment.GetEnvironmentVariable("FTR_SETUP_PATH") ?? "";
            string registered = Environment.GetEnvironmentVariable("FTR_SETUP_REGISTERED_PATH") ?? "";
            return Validate(path, registered, args[0] == "prepare", limit);
        }
        catch (Exception error)
        {
            if (error is ArgumentException || error is NotSupportedException)
                return 10;
            if (error is IOException || error is UnauthorizedAccessException ||
                error is System.Security.SecurityException || error is InvalidOperationException)
                return 15;
            throw;
        }
    }

    private static int Validate(string path, string registered, bool prepare, int limit)
    {
        if (!Regex.IsMatch(path, @"\A[A-Za-z]:\\") || path.Length > limit || path.Length <= 3)
            return 10;
        string root = path.Substring(0, 3);
        string[] parts = path.Substring(3).Split('\\');
        foreach (string part in parts)
        {
            if (part.Length == 0 || part.EndsWith(".") || part.EndsWith(" ") ||
                part.IndexOfAny(Path.GetInvalidFileNameChars()) >= 0 ||
                Regex.IsMatch(part, @"\A(?:CON|PRN|AUX|NUL|COM[1-9¹²³]|LPT[1-9¹²³])(?:\.|\z)", RegexOptions.IgnoreCase))
                return 10;
        }
        string windows = Environment.GetFolderPath(Environment.SpecialFolder.Windows);
        if (Same(path, windows) || path.StartsWith(windows + "\\", StringComparison.OrdinalIgnoreCase))
            return 10;
        if (registered.Length != 0 && !Same(path, registered))
            return 12;

        // Require a real volume mount, not a network path, virtual drive letter, or file-system redirect.
        var drive = new DriveInfo(root);
        var volume = new StringBuilder(64);
        if (drive.DriveType != DriveType.Fixed ||
            !GetVolumeNameForVolumeMountPointW(root, volume, volume.Capacity) ||
            !Same(drive.DriveFormat, "NTFS"))
            return 11;

        var held = new List<SafeFileHandle>();
        try
        {
            string current = root;
            for (int i = -1; i < parts.Length; i++)
            {
                bool leaf = i == parts.Length - 1;
                if (i >= 0)
                    current = Path.Combine(current, parts[i]);
                SafeFileHandle directory = Open(current, i >= 0);
                if (directory == null)
                {
                    if (!prepare) return 0; // All existing ancestors have already passed.
                    Directory.CreateDirectory(current, NewDirectorySecurity());
                    directory = Open(current, false);
                }
                held.Add(directory);
                if (i == -1)
                {
                    var opened = new StringBuilder(64);
                    uint length = GetFinalPathNameByHandleW(directory, opened, (uint)opened.Capacity, 1);
                    if (length == 0 || length >= opened.Capacity ||
                        !Same(volume.ToString().TrimEnd('\\'), opened.ToString().TrimEnd('\\')))
                        return 11;
                }
                if (!IsProtected(directory, i == -1, leaf)) return 13;
            }

            if (registered.Length == 0)
                using (var entries = Directory.EnumerateFileSystemEntries(path).GetEnumerator())
                    if (entries.MoveNext()) return 14;
            return 0;
        }
        finally
        {
            for (int i = held.Count - 1; i >= 0; i--)
                held[i].Dispose();
        }
    }

    private static DirectorySecurity NewDirectorySecurity()
    {
        var security = new DirectorySecurity();
        security.SetOwner(new SecurityIdentifier(Administrators));
        security.SetAccessRuleProtection(true, false);
        var children = InheritanceFlags.ContainerInherit | InheritanceFlags.ObjectInherit;
        foreach (string sid in new[] { Administrators, SystemAccount, "S-1-5-32-545" })
            security.AddAccessRule(new FileSystemAccessRule(new SecurityIdentifier(sid),
                sid == "S-1-5-32-545" ? FileSystemRights.ReadAndExecute : FileSystemRights.FullControl,
                children, PropagationFlags.None, AccessControlType.Allow));
        return security;
    }

    private static bool IsProtected(SafeFileHandle directory, bool root, bool leaf)
    {
        // Check attributes and ACL on the same no-follow handle, not by reopening a path.
        FileInformation info;
        if (!GetFileInformationByHandle(directory, out info))
            throw new IOException("Cannot read directory attributes.");
        if ((info.Attributes & (0x10 | 0x400)) != 0x10) return false;
        IntPtr owner, group, dacl, sacl, descriptor;
        if (GetSecurityInfo(directory, 1, 5, out owner, out group, out dacl, out sacl, out descriptor) != 0)
            throw new IOException("Cannot read directory security.");
        try
        {
            var binary = new byte[GetSecurityDescriptorLength(descriptor)];
            Marshal.Copy(descriptor, binary, 0, binary.Length);
            var security = new RawSecurityDescriptor(binary, 0);
            if (security.Owner == null || !Trusted(security.Owner.Value) || security.DiscretionaryAcl == null)
                return false;
            int forbidden = DeleteChild | AclWrite | (root ? 0 : DirectoryWrite);
            foreach (GenericAce rule in security.DiscretionaryAcl)
            {
                bool inheritOnly = (rule.AceFlags & AceFlags.InheritOnly) != 0;
                if (inheritOnly && !leaf) continue;
                var access = rule as QualifiedAce;
                if (access == null) return false; // Refuse ACL forms we cannot verify.
                if (access.AceQualifier != AceQualifier.AccessAllowed) continue;
                string sid = access.SecurityIdentifier.Value;
                if (inheritOnly && sid == CreatorOwner) continue;
                if (!Trusted(sid) && (access.AccessMask & forbidden) != 0) return false;
            }
            return true;
        }
        finally { LocalFree(descriptor); }
    }

    private static SafeFileHandle Open(string path, bool allowMissing)
    {
        // Read owner/ACL and attributes; don't follow links or allow rename while validating.
        SafeFileHandle handle = CreateFileW(path, 0x20080, 3, IntPtr.Zero, 3, 0x02200000, IntPtr.Zero);
        if (!handle.IsInvalid) return handle;
        int error = Marshal.GetLastWin32Error();
        handle.Dispose();
        if (allowMissing && (error == 2 || error == 3)) return null;
        throw new IOException("Cannot open installation directory (Windows error " + error + ").");
    }

    private static bool Same(string a, string b) { return String.Equals(a, b, StringComparison.OrdinalIgnoreCase); }
    private static bool Trusted(string sid) { return sid == Administrators || sid == SystemAccount || sid == TrustedInstaller; }

    [StructLayout(LayoutKind.Sequential)]
    private struct FileInformation
    {
        public uint Attributes;
        public System.Runtime.InteropServices.ComTypes.FILETIME Created, Accessed, Written;
        public uint Volume, SizeHigh, SizeLow, Links, IndexHigh, IndexLow;
    }
    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true, ExactSpelling = true)]
    private static extern SafeFileHandle CreateFileW(string path, uint access, uint share, IntPtr security,
        uint disposition, uint flags, IntPtr template);
    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, ExactSpelling = true)]
    private static extern bool GetVolumeNameForVolumeMountPointW(string path, StringBuilder name, int length);
    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, ExactSpelling = true)]
    private static extern uint GetFinalPathNameByHandleW(SafeFileHandle file, StringBuilder name, uint length, uint flags);
    [DllImport("kernel32.dll")]
    private static extern bool GetFileInformationByHandle(SafeFileHandle file, out FileInformation info);
    [DllImport("advapi32.dll")]
    private static extern uint GetSecurityInfo(SafeFileHandle file, uint objectType, uint flags,
        out IntPtr owner, out IntPtr group, out IntPtr dacl, out IntPtr sacl, out IntPtr descriptor);
    [DllImport("advapi32.dll")]
    private static extern int GetSecurityDescriptorLength(IntPtr descriptor);
    [DllImport("kernel32.dll")]
    private static extern IntPtr LocalFree(IntPtr ptr);
}
