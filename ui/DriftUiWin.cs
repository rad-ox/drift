using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Runtime.InteropServices;
using System.Runtime.Serialization;
using System.Runtime.Serialization.Json;
using System.Text;
using System.Text.RegularExpressions;
using System.Threading;
using System.Windows;
using System.Windows.Automation;
using System.Windows.Controls;
using System.Windows.Controls.Primitives;
using System.Windows.Input;
using System.Windows.Interop;
using System.Windows.Media;
using System.Windows.Media.Animation;
using System.Windows.Shapes;
using System.Windows.Threading;
using Microsoft.Win32;

[assembly: System.Runtime.Versioning.TargetFramework(".NETFramework,Version=v4.8", FrameworkDisplayName = ".NET Framework 4.8")]

namespace DriftDesktopUi
{
    [DataContract]
    public sealed class UiOptionItem
    {
        [DataMember(Name = "id")] public string Id;
        [DataMember(Name = "does")] public string Does;
        [DataMember(Name = "summary")] public string Summary;
        [DataMember(Name = "chips")] public List<string> Chips;
        [DataMember(Name = "effort")] public string Effort;
        [DataMember(Name = "risk_level")] public int RiskLevel;
        [DataMember(Name = "undo")] public string Undo;
        [DataMember(Name = "dominated_by")] public List<string> DominatedBy;
        [DataMember(Name = "is_recommended")] public bool IsRecommended;
        [DataMember(Name = "is_pareto")] public bool IsPareto;
    }

    [DataContract]
    public sealed class UiKvPair
    {
        [DataMember(Name = "key")] public string Key;
        [DataMember(Name = "val")] public string Val;
        [DataMember(Name = "relaxed")] public bool Relaxed;
    }

    [DataContract]
    public sealed class UiRelaxationItem
    {
        [DataMember(Name = "title")] public string Title;
        [DataMember(Name = "detail")] public string Detail;
    }

    [DataContract]
    public sealed class UiCaseRow
    {
        [DataMember(Name = "id")] public string Id;
        [DataMember(Name = "badge")] public string Badge;
        [DataMember(Name = "when_text")] public string WhenText;
        [DataMember(Name = "then_text")] public string ThenText;
        [DataMember(Name = "when_pairs")] public List<UiKvPair> WhenPairs;
        [DataMember(Name = "then_pairs")] public List<UiKvPair> ThenPairs;
    }

    [DataContract]
    public sealed class UiContractPanel
    {
        [DataMember(Name = "id")] public string Id;
        [DataMember(Name = "file")] public string File;
        [DataMember(Name = "intent")] public string Intent;
        [DataMember(Name = "approval")] public string Approval;
        [DataMember(Name = "change_kind")] public string ChangeKind;
        [DataMember(Name = "has_baseline")] public bool HasBaseline;
        [DataMember(Name = "has_clause_counts")] public bool HasClauseCounts;
        [DataMember(Name = "active_cases_count")] public int ActiveCasesCount;
        [DataMember(Name = "added_cases_count")] public int AddedCasesCount;
        [DataMember(Name = "invariants_count")] public int InvariantsCount;
        [DataMember(Name = "budgets_count")] public int BudgetsCount;
        [DataMember(Name = "formal_count")] public int FormalCount;
        [DataMember(Name = "surface")] public string Surface;
        [DataMember(Name = "coarsened")] public List<string> Coarsened;
        [DataMember(Name = "witnesses")] public List<string> Witnesses;
        [DataMember(Name = "relaxations")] public List<UiRelaxationItem> Relaxations;
        [DataMember(Name = "impacts")] public List<string> Impacts;
        [DataMember(Name = "cases")] public List<UiCaseRow> Cases;
        [DataMember(Name = "code")] public List<string> Code;
        [DataMember(Name = "reads")] public List<string> Reads;
        [DataMember(Name = "writes")] public List<string> Writes;
    }

    [DataContract]
    public sealed class UiExecChoiceItem
    {
        [DataMember(Name = "contract_id")] public string ContractId;
        [DataMember(Name = "card_id")] public string CardId;
        [DataMember(Name = "pick")] public string Pick;
        [DataMember(Name = "ask")] public string Ask;
        [DataMember(Name = "why")] public string Why;
        [DataMember(Name = "does")] public string Does;
        [DataMember(Name = "effort")] public string Effort;
        [DataMember(Name = "risk_level")] public int RiskLevel;
        [DataMember(Name = "undo")] public string Undo;
        [DataMember(Name = "cases")] public List<string> Cases;
    }

    [DataContract]
    public sealed class UiTargetItem
    {
        [DataMember(Name = "path")] public string Path;
        [DataMember(Name = "behavior_digest")] public string BehaviorDigest;
        [DataMember(Name = "assurance_digest")] public string AssuranceDigest;
    }

    [DataContract]
    public sealed class UiCardItem
    {
        [DataMember(Name = "contract_id")] public string ContractId;
        [DataMember(Name = "contract_file")] public string ContractFile;
        [DataMember(Name = "contract_intent")] public string ContractIntent;
        [DataMember(Name = "card_kind")] public string CardKind;
        [DataMember(Name = "card_id")] public string CardId;
        [DataMember(Name = "ask")] public string Ask;
        [DataMember(Name = "why")] public string Why;
        [DataMember(Name = "cases")] public List<string> Cases;
        [DataMember(Name = "owner")] public string Owner;
        [DataMember(Name = "disposition")] public string Disposition;
        [DataMember(Name = "proposed_pick")] public string ProposedPick;
        [DataMember(Name = "recommended_option")] public string RecommendedOption;
        [DataMember(Name = "recommendation_basis")] public string RecommendationBasis;
        [DataMember(Name = "changed_since_prior")] public bool ChangedSincePrior;
        [DataMember(Name = "impacts")] public List<string> Impacts;
        [DataMember(Name = "options")] public List<UiOptionItem> Options;
    }

    [DataContract]
    public sealed class UiRequestEnvelope
    {
        [DataMember(Name = "schema")] public string Schema;
        [DataMember(Name = "request_id")] public string RequestId;
        [DataMember(Name = "area_name")] public string AreaName;
        [DataMember(Name = "project_name")] public string ProjectName;
        [DataMember(Name = "worktree_name")] public string WorktreeName;
        [DataMember(Name = "is_linked_worktree")] public bool IsLinkedWorktree;
        [DataMember(Name = "git_branch")] public string GitBranch;
        [DataMember(Name = "workspace_path")] public string WorkspacePath;
        [DataMember(Name = "edition")] public string Edition;
        [DataMember(Name = "theme")] public string Theme;
        [DataMember(Name = "owner")] public string Owner;
        [DataMember(Name = "review_ref")] public string ReviewRef;
        [DataMember(Name = "quiet_arm_ms")] public int QuietArmMs;
        [DataMember(Name = "timeout_s")] public int TimeoutSec;
        [DataMember(Name = "sentinel_path")] public string SentinelPath;
        [DataMember(Name = "needs_owner_enrollment")] public bool NeedsOwnerEnrollment;
        [DataMember(Name = "suggested_owner")] public string SuggestedOwner;
        [DataMember(Name = "policy_approvers")] public List<string> PolicyApprovers;
        [DataMember(Name = "can_seal_directly")] public bool CanSealDirectly;
        [DataMember(Name = "kernel_banner")] public string KernelBanner;
        [DataMember(Name = "kernel_warning")] public bool KernelWarning;
        [DataMember(Name = "targets_count")] public int TargetsCount;
        [DataMember(Name = "unchanged_count")] public int UnchangedCount;
        [DataMember(Name = "relaxed_count")] public int RelaxedCount;
        [DataMember(Name = "removed_count")] public int RemovedCount;
        [DataMember(Name = "hidden_count")] public int HiddenCount;
        [DataMember(Name = "banner_impacts")] public List<string> BannerImpacts;
        [DataMember(Name = "impacts")] public List<string> Impacts;
        [DataMember(Name = "cases_tab")] public string CasesTab;
        [DataMember(Name = "perimeter_tab")] public string PerimeterTab;
        [DataMember(Name = "targets_tab")] public string TargetsTab;
        [DataMember(Name = "contract_panels")] public List<UiContractPanel> ContractPanels;
        [DataMember(Name = "exec_choices")] public List<UiExecChoiceItem> ExecChoices;
        [DataMember(Name = "target_items")] public List<UiTargetItem> TargetItems;
        [DataMember(Name = "targets")] public List<UiTargetItem> TargetsAlt;
        [DataMember(Name = "claim_limits")] public List<string> ClaimLimits;
        [DataMember(Name = "cards")] public List<UiCardItem> Cards;
    }

    [DataContract]
    public sealed class UiSelectionItem
    {
        [DataMember(Name = "contract_id")] public string ContractId;
        [DataMember(Name = "card_kind")] public string CardKind;
        [DataMember(Name = "card_id")] public string CardId;
        [DataMember(Name = "selected_pick")] public string SelectedPick;
        [DataMember(Name = "answer")] public string Answer;
    }

    [DataContract]
    public sealed class UiGestureEnvelope
    {
        [DataMember(Name = "schema")] public string Schema;
        [DataMember(Name = "request_id")] public string RequestId;
        [DataMember(Name = "action")] public string Action;
        [DataMember(Name = "confirmed_review_ref")] public string ConfirmedReviewRef;
        [DataMember(Name = "confirmed_owner")] public string ConfirmedOwner;
        [DataMember(Name = "note")] public string Note;
        [DataMember(Name = "selections")] public List<UiSelectionItem> Selections;
    }

    internal static class NativeWin32
    {
        [DllImport("user32.dll")]
        internal static extern bool ReleaseCapture();

        [DllImport("user32.dll")]
        internal static extern IntPtr SendMessage(IntPtr hWnd, uint Msg, IntPtr wParam, IntPtr lParam);

        [DllImport("kernel32.dll")]
        private static extern uint GetCurrentProcessId();

        [DllImport("kernel32.dll")]
        private static extern bool ProcessIdToSessionId(uint dwProcessId, out uint pSessionId);

        [DllImport("wtsapi32.dll", SetLastError = true)]
        private static extern bool WTSQuerySessionInformation(IntPtr hServer, int sessionId, int wtsInfoClass, out IntPtr ppBuffer, out int pBytesReturned);

        [DllImport("wtsapi32.dll")]
        private static extern void WTSFreeMemory(IntPtr pMemory);

        [DllImport("user32.dll", SetLastError = true)]
        private static extern IntPtr OpenInputDesktop(uint dwFlags, bool fInherit, uint dwDesiredAccess);

        [DllImport("user32.dll", SetLastError = true)]
        private static extern bool CloseDesktop(IntPtr hDesktop);

        [DllImport("user32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
        private static extern bool GetUserObjectInformation(IntPtr hObj, int nIndex, StringBuilder pvInfo, int nLength, out int lpnLengthNeeded);

        internal static bool ProbeInteractiveDesktop(out string reason)
        {
            if (!Environment.UserInteractive)
            {
                reason = "non_interactive_process";
                return false;
            }
            uint sessionId;
            if (ProcessIdToSessionId(GetCurrentProcessId(), out sessionId) && sessionId == 0)
            {
                reason = "session_zero_service";
                return false;
            }
            IntPtr wtsBuf = IntPtr.Zero;
            int wtsBytes = 0;
            try
            {
                if (WTSQuerySessionInformation(IntPtr.Zero, -1, 8, out wtsBuf, out wtsBytes) && wtsBuf != IntPtr.Zero && wtsBytes >= 4)
                {
                    int connState = Marshal.ReadInt32(wtsBuf);
                    if (connState != 0)
                    {
                        reason = "session_disconnected";
                        return false;
                    }
                }
            }
            catch { }
            finally
            {
                if (wtsBuf != IntPtr.Zero) WTSFreeMemory(wtsBuf);
            }

            IntPtr hDesk = OpenInputDesktop(0, false, 0x0100);
            if (hDesk == IntPtr.Zero)
            {
                reason = "desktop_locked_or_inaccessible";
                return false;
            }
            try
            {
                StringBuilder nameBuf = new StringBuilder(128);
                int needed;
                if (GetUserObjectInformation(hDesk, 2, nameBuf, nameBuf.Capacity * 2, out needed))
                {
                    string dName = nameBuf.ToString();
                    if (!string.IsNullOrEmpty(dName) && !string.Equals(dName, "Default", StringComparison.OrdinalIgnoreCase))
                    {
                        reason = "non_default_desktop_" + dName;
                        return false;
                    }
                }
            }
            finally
            {
                CloseDesktop(hDesk);
            }

            if (SystemParameters.HighContrast)
            {
                reason = "high_contrast_accessibility_fallback";
                return false;
            }
            reason = "windows_active_desktop";
            return true;
        }

        internal static bool IsSystemLightTheme()
        {
            try
            {
                object val = Registry.GetValue(@"HKEY_CURRENT_USER\Software\Microsoft\Windows\CurrentVersion\Themes\Personalize", "AppsUseLightTheme", 0);
                if (val is int) return ((int)val) == 1;
            }
            catch { }
            return false;
        }
    }

    public static class TextSanitizer
    {
        public static string SanitizeText(string raw)
        {
            if (string.IsNullOrEmpty(raw)) return string.Empty;
            StringBuilder sb = new StringBuilder(raw.Length);
            for (int i = 0; i < raw.Length; i++)
            {
                char c = raw[i];
                if (c == '\r') continue;
                if (c == '\t') { sb.Append("  "); continue; }
                if (c == '\n') { sb.Append('\n'); continue; }
                if (c < 0x20 || (c >= 0x7F && c <= 0x9F)) continue;
                if (c == '\u2028' || c == '\u2029' || c == '\uFEFF' || (c >= '\u200B' && c <= '\u200D')) continue;
                if ((c >= '\u202A' && c <= '\u202E') || (c >= '\u2066' && c <= '\u206F') ||
                    c == '\u200E' || c == '\u200F' || c == '\u061C')
                {
                    continue;
                }
                sb.Append(c);
            }
            return sb.ToString();
        }
    }

    internal sealed class DossierPalette
    {
        public bool IsLight;

        // Spine brushes & atmospheric gradients
        public SolidColorBrush SpineSolidFallback;
        public Brush SpineBgBrush;
        public Brush SpineGlowBrush;
        public SolidColorBrush SpineWell;
        public Brush SpineActiveBrush;
        public SolidColorBrush SpineBorder;
        public SolidColorBrush SpineActiveBorder;
        public SolidColorBrush SpineInk;
        public SolidColorBrush SpineSub;
        public SolidColorBrush SpineDim;
        public SolidColorBrush SpineCopper;
        public SolidColorBrush SpineMint;
        public SolidColorBrush SpineMintBright;

        // Outer machined rim & specular highlights
        public Brush OuterRimBrush;
        public SolidColorBrush InnerSpecularRim;
        public SolidColorBrush InnerBevel;

        // Stage atmospheric gradient & card surfaces
        public SolidColorBrush StageSolidFallback;
        public Brush StageBgBrush;
        public SolidColorBrush CardBg;
        public Brush CardIdleBrush;
        public Brush CardHoverBrush;
        public Brush CardSelectedBrush;
        public Brush CrownBarActiveBrush;
        public SolidColorBrush CrownBarIdle;
        public Brush HorizonBeamBrush;
        public Brush ContextWashBrush;
        public Brush AmberWashBrush;
        public Brush MintWashBrush;

        public SolidColorBrush WellBg;
        public SolidColorBrush BtnBg;
        public SolidColorBrush BtnHover;
        public SolidColorBrush BorderSubtle;
        public SolidColorBrush BorderCard;

        public SolidColorBrush InkPrimary;
        public SolidColorBrush InkBody;
        public SolidColorBrush InkMuted;

        public SolidColorBrush Copper;
        public SolidColorBrush CopperStroke;
        public Brush CopperCtaBrush;
        public Brush CopperCtaHoverBrush;
        public SolidColorBrush CopperSoft;
        public SolidColorBrush CopperBorder;
        public SolidColorBrush OnCopper;

        public SolidColorBrush Mint;
        public SolidColorBrush MintBright;
        public Brush MintCtaBrush;
        public Brush MintCtaHoverBrush;
        public SolidColorBrush MintSoft;
        public SolidColorBrush MintBorder;
        public SolidColorBrush OnMint;

        public SolidColorBrush Amber;
        public SolidColorBrush AmberBg;
        public SolidColorBrush AmberBorder;
        public SolidColorBrush Coral;
        public SolidColorBrush PipOff;

        internal static SolidColorBrush Rgb(byte r, byte g, byte b)
        {
            SolidColorBrush br = new SolidColorBrush(Color.FromRgb(r, g, b));
            br.Freeze();
            return br;
        }

        internal static SolidColorBrush Rgba(byte a, byte r, byte g, byte b)
        {
            SolidColorBrush br = new SolidColorBrush(Color.FromArgb(a, r, g, b));
            br.Freeze();
            return br;
        }

        private static LinearGradientBrush VGrad(Color top, Color bot)
        {
            LinearGradientBrush br = new LinearGradientBrush(top, bot, new Point(0.5, 0.0), new Point(0.5, 1.0));
            br.Freeze();
            return br;
        }

        private static LinearGradientBrush HWash(Color tint, byte leftAlpha, byte midAlpha, Color baseCol)
        {
            LinearGradientBrush br = new LinearGradientBrush { StartPoint = new Point(0, 0.5), EndPoint = new Point(1, 0.5) };
            br.GradientStops.Add(new GradientStop(MergeAlpha(baseCol, tint, leftAlpha), 0.0));
            br.GradientStops.Add(new GradientStop(MergeAlpha(baseCol, tint, midAlpha), 0.48));
            br.GradientStops.Add(new GradientStop(baseCol, 1.0));
            br.Freeze();
            return br;
        }

        private static Color MergeAlpha(Color bg, Color fg, byte alpha)
        {
            double a = alpha / 255.0;
            byte r = (byte)Math.Min(255, Math.Round(bg.R * (1.0 - a) + fg.R * a));
            byte g = (byte)Math.Min(255, Math.Round(bg.G * (1.0 - a) + fg.G * a));
            byte b = (byte)Math.Min(255, Math.Round(bg.B * (1.0 - a) + fg.B * a));
            return Color.FromRgb(r, g, b);
        }

        public static DossierPalette Create(bool light)
        {
            DossierPalette p = new DossierPalette { IsLight = light };

            // Rich Basalt-Obsidian Spine with subtle warm copper-verdigris ambient glow
            p.SpineSolidFallback = Rgb(17, 20, 25);
            p.SpineBgBrush = VGrad(Color.FromRgb(23, 27, 34), Color.FromRgb(14, 17, 22));
            RadialGradientBrush sGlow = new RadialGradientBrush
            {
                Center = new Point(0.18, 0.08),
                GradientOrigin = new Point(0.18, 0.08),
                RadiusX = 0.85,
                RadiusY = 0.45
            };
            sGlow.GradientStops.Add(new GradientStop(Color.FromArgb(34, 232, 167, 109), 0.0));
            sGlow.GradientStops.Add(new GradientStop(Color.FromArgb(16, 88, 220, 195), 0.55));
            sGlow.GradientStops.Add(new GradientStop(Color.FromArgb(0, 14, 17, 22), 1.0));
            sGlow.Freeze();
            p.SpineGlowBrush = sGlow;

            p.SpineWell = Rgb(22, 26, 33);
            LinearGradientBrush sAct = new LinearGradientBrush { StartPoint = new Point(0, 0.5), EndPoint = new Point(1, 0.5) };
            sAct.GradientStops.Add(new GradientStop(Color.FromRgb(38, 33, 29), 0.0));
            sAct.GradientStops.Add(new GradientStop(Color.FromRgb(26, 31, 40), 1.0));
            sAct.Freeze();
            p.SpineActiveBrush = sAct;

            p.SpineBorder = Rgb(39, 45, 55);
            p.SpineActiveBorder = Rgb(128, 92, 64);
            p.SpineInk = Rgb(245, 243, 238);
            p.SpineSub = Rgb(178, 182, 190);
            p.SpineDim = Rgb(126, 132, 142);
            p.SpineCopper = Rgb(232, 167, 109);
            p.SpineMint = Rgb(88, 220, 195);
            p.SpineMintBright = Rgb(112, 246, 217);

            LinearGradientBrush beam = new LinearGradientBrush(Color.FromRgb(232, 167, 109), Color.FromRgb(88, 220, 195), 0.0);
            beam.Freeze();
            p.HorizonBeamBrush = beam;

            LinearGradientBrush crown = new LinearGradientBrush(Color.FromRgb(232, 167, 109), Color.FromRgb(112, 246, 217), 0.0);
            crown.Freeze();
            p.CrownBarActiveBrush = crown;

            if (light)
            {
                p.StageSolidFallback = Rgb(244, 241, 234);
                RadialGradientBrush stRad = new RadialGradientBrush
                {
                    Center = new Point(0.48, 0.16),
                    GradientOrigin = new Point(0.48, 0.16),
                    RadiusX = 0.95,
                    RadiusY = 0.95
                };
                stRad.GradientStops.Add(new GradientStop(Color.FromRgb(251, 249, 244), 0.0));
                stRad.GradientStops.Add(new GradientStop(Color.FromRgb(244, 240, 232), 0.62));
                stRad.GradientStops.Add(new GradientStop(Color.FromRgb(234, 228, 216), 1.0));
                stRad.Freeze();
                p.StageBgBrush = stRad;

                LinearGradientBrush rimL = new LinearGradientBrush { StartPoint = new Point(0, 0), EndPoint = new Point(1, 1) };
                rimL.GradientStops.Add(new GradientStop(Color.FromRgb(196, 134, 82), 0.0));
                rimL.GradientStops.Add(new GradientStop(Color.FromRgb(196, 189, 174), 0.5));
                rimL.GradientStops.Add(new GradientStop(Color.FromRgb(56, 164, 142), 1.0));
                rimL.Freeze();
                p.OuterRimBrush = rimL;
                p.InnerSpecularRim = Rgba(185, 255, 255, 255);
                p.InnerBevel = Rgba(140, 255, 255, 255);

                p.CardBg = Rgb(255, 255, 255);
                p.CardIdleBrush = VGrad(Color.FromRgb(255, 255, 255), Color.FromRgb(251, 249, 244));
                p.CardHoverBrush = HWash(Color.FromRgb(200, 108, 42), 20, 6, Color.FromRgb(255, 253, 249));
                p.CardSelectedBrush = HWash(Color.FromRgb(22, 148, 122), 26, 8, Color.FromRgb(252, 255, 253));
                p.CrownBarIdle = Rgb(201, 192, 174);

                p.WellBg = Rgb(232, 226, 212);
                p.ContextWashBrush = HWash(Color.FromRgb(200, 108, 42), 20, 6, Color.FromRgb(244, 240, 232));
                p.AmberWashBrush = HWash(Color.FromRgb(217, 142, 26), 34, 10, Color.FromRgb(244, 240, 232));
                p.MintWashBrush = HWash(Color.FromRgb(22, 148, 122), 28, 8, Color.FromRgb(244, 240, 232));

                p.BtnBg = Rgb(233, 228, 217);
                p.BtnHover = Rgb(224, 218, 204);
                p.BorderSubtle = Rgb(214, 207, 193);
                p.BorderCard = Rgb(198, 190, 174);

                p.InkPrimary = Rgb(22, 25, 30);
                p.InkBody = Rgb(62, 68, 78);
                p.InkMuted = Rgb(91, 98, 110);

                p.Copper = Rgb(156, 65, 13);
                p.CopperStroke = Rgb(172, 92, 42);
                p.CopperCtaBrush = VGrad(Color.FromRgb(36, 42, 55), Color.FromRgb(22, 26, 35));
                p.CopperCtaHoverBrush = VGrad(Color.FromRgb(44, 51, 67), Color.FromRgb(27, 32, 43));
                p.CopperSoft = Rgb(246, 234, 222);
                p.CopperBorder = Rgb(186, 120, 76);
                p.OnCopper = Rgb(246, 244, 238);

                p.Mint = Rgb(11, 102, 82);
                p.MintBright = Rgb(9, 89, 71);
                p.MintCtaBrush = VGrad(Color.FromRgb(20, 56, 49), Color.FromRgb(12, 35, 31));
                p.MintCtaHoverBrush = VGrad(Color.FromRgb(25, 69, 60), Color.FromRgb(16, 44, 39));
                p.MintSoft = Rgb(224, 243, 238);
                p.MintBorder = Rgb(92, 168, 150);
                p.OnMint = Rgb(238, 252, 249);

                p.Amber = Rgb(134, 84, 18);
                p.AmberBg = Rgb(249, 241, 226);
                p.AmberBorder = Rgb(206, 168, 108);
                p.Coral = Rgb(194, 61, 42);
                p.PipOff = Rgb(216, 210, 196);
                return p;
            }

            // Atmospheric DRIFT Observatory Dark Palette (burnished obsidian-copper + deep verdigris)
            p.StageSolidFallback = Rgb(23, 26, 33);
            RadialGradientBrush darkRad = new RadialGradientBrush
            {
                Center = new Point(0.52, 0.14),
                GradientOrigin = new Point(0.52, 0.14),
                RadiusX = 0.95,
                RadiusY = 0.95
            };
            darkRad.GradientStops.Add(new GradientStop(Color.FromRgb(33, 38, 48), 0.0));
            darkRad.GradientStops.Add(new GradientStop(Color.FromRgb(23, 26, 33), 0.58));
            darkRad.GradientStops.Add(new GradientStop(Color.FromRgb(17, 20, 25), 1.0));
            darkRad.Freeze();
            p.StageBgBrush = darkRad;

            LinearGradientBrush rimD = new LinearGradientBrush { StartPoint = new Point(0, 0), EndPoint = new Point(1, 1) };
            rimD.GradientStops.Add(new GradientStop(Color.FromArgb(190, 232, 167, 109), 0.0));
            rimD.GradientStops.Add(new GradientStop(Color.FromArgb(145, 52, 58, 70), 0.50));
            rimD.GradientStops.Add(new GradientStop(Color.FromArgb(180, 88, 220, 195), 1.0));
            rimD.Freeze();
            p.OuterRimBrush = rimD;
            p.InnerSpecularRim = Rgba(34, 255, 255, 255);
            p.InnerBevel = Rgba(20, 255, 255, 255);

            p.CardBg = Rgb(25, 29, 37);
            p.CardIdleBrush = VGrad(Color.FromRgb(31, 36, 45), Color.FromRgb(22, 26, 33));
            p.CardHoverBrush = HWash(Color.FromRgb(232, 167, 109), 24, 7, Color.FromRgb(25, 29, 37));
            p.CardSelectedBrush = HWash(Color.FromRgb(88, 220, 195), 28, 9, Color.FromRgb(21, 29, 34));
            p.CrownBarIdle = Rgb(44, 50, 62);

            p.WellBg = Rgb(16, 20, 26);
            LinearGradientBrush ambFade = new LinearGradientBrush { StartPoint = new Point(0, 0.5), EndPoint = new Point(1, 0.5) };
            ambFade.GradientStops.Add(new GradientStop(Color.FromArgb(28, 223, 180, 120), 0.0));
            ambFade.GradientStops.Add(new GradientStop(Color.FromArgb(8, 223, 180, 120), 0.60));
            ambFade.GradientStops.Add(new GradientStop(Color.FromArgb(0, 23, 26, 33), 1.0));
            ambFade.Freeze();
            p.AmberWashBrush = ambFade;

            p.ContextWashBrush = HWash(Color.FromRgb(232, 167, 109), 18, 5, Color.FromRgb(21, 25, 32));
            p.MintWashBrush = HWash(Color.FromRgb(88, 220, 195), 22, 7, Color.FromRgb(18, 28, 28));

            p.BtnBg = Rgb(27, 32, 41);
            p.BtnHover = Rgb(35, 41, 52);
            p.BorderSubtle = Rgb(38, 44, 55);
            p.BorderCard = Rgb(46, 53, 66);

            p.InkPrimary = Rgb(245, 243, 238);
            p.InkBody = Rgb(206, 202, 193);
            p.InkMuted = Rgb(147, 154, 168);

            p.Copper = Rgb(232, 167, 109);
            p.CopperStroke = Rgb(176, 122, 78);
            p.CopperCtaBrush = VGrad(Color.FromRgb(34, 40, 54), Color.FromRgb(20, 24, 33));
            p.CopperCtaHoverBrush = VGrad(Color.FromRgb(43, 51, 68), Color.FromRgb(25, 30, 41));
            p.CopperSoft = Rgb(38, 30, 24);
            p.CopperBorder = Rgb(156, 108, 70);
            p.OnCopper = Rgb(246, 244, 238);

            p.Mint = Rgb(88, 220, 195);
            p.MintBright = Rgb(118, 247, 220);
            p.MintCtaBrush = VGrad(Color.FromRgb(22, 50, 45), Color.FromRgb(13, 31, 28));
            p.MintCtaHoverBrush = VGrad(Color.FromRgb(28, 62, 56), Color.FromRgb(17, 40, 35));
            p.MintSoft = Rgb(17, 38, 34);
            p.MintBorder = Rgb(62, 154, 135);
            p.OnMint = Rgb(238, 252, 249);

            p.Amber = Rgb(223, 180, 120);
            p.AmberBg = Rgb(36, 30, 22);
            p.AmberBorder = Rgb(118, 90, 52);
            p.Coral = Rgb(232, 116, 100);
            p.PipOff = Rgb(36, 42, 52);
            return p;
        }
    }

    internal sealed class DossierButton
    {
        public Button Control;
        public Border Surface;
        public TranslateTransform Lift;
        public ScaleTransform PressScale;
        public TextBlock Label;
        public Brush NormalBg;
        public Brush HoverBg;
        public Brush NormalBorder;
        public Brush FocusBorder;
        public Brush NormalFg;
        public bool IsEnabledState = true;
        public bool IsArmedVisual = true;

        public void SyncVisual(bool animateLift, bool allowMotion)
        {
            Control.IsEnabled = IsEnabledState;
            bool hov = Control.IsMouseOver && IsEnabledState;
            bool keyFocus = Control.IsKeyboardFocused && (InputManager.Current != null && InputManager.Current.MostRecentInputDevice is KeyboardDevice);
            Surface.Background = hov ? HoverBg : NormalBg;
            Surface.BorderBrush = keyFocus ? FocusBorder : (hov ? FocusBorder : NormalBorder);
            Surface.BorderThickness = new Thickness(keyFocus ? 2.0 : 1.5);
            Label.Foreground = NormalFg;
            Surface.Opacity = (!IsEnabledState) ? 0.42 : (IsArmedVisual ? 1.0 : 0.62);
            Control.Cursor = IsEnabledState ? Cursors.Hand : Cursors.Arrow;

            if (Lift != null)
            {
                double targetY = hov ? -1.0 : 0.0;
                if (animateLift && allowMotion)
                {
                    Lift.BeginAnimation(TranslateTransform.YProperty, new DoubleAnimation(targetY, new Duration(TimeSpan.FromMilliseconds(120)))
                    {
                        EasingFunction = new CubicEase { EasingMode = EasingMode.EaseOut }
                    });
                }
                else
                {
                    Lift.BeginAnimation(TranslateTransform.YProperty, null);
                    Lift.Y = targetY;
                }
            }
        }
    }

    internal sealed class OptionRowHandle
    {
        public string OptionId;
        public int Index;
        public UiOptionItem Option;
        public bool IsDominated;
        public UIElement DimHost;
        public WrapPanel DeltaHost;
        public string BaseAutomationName;
        public RadioButton Radio;
        public Border CardBorder;
        public RadialGradientBrush SpotlightBrush;
        public Border SpotlightLayer;
        public Border CrownBar;
        public TranslateTransform Lift;
        public Border Keycap;
        public TextBlock KeycapText;
        public TextBlock ProseText;
        public Polygon OuterGem;
        public Polygon InnerGem;
    }

    internal sealed class DecisionWindow : Window
    {
        private static readonly FontFamily SansFont = new FontFamily("Segoe UI");
        private static readonly FontFamily MonoFont = new FontFamily("Cascadia Mono, Consolas");
        private static readonly HashSet<string> KnownAcronyms = new HashSet<string>(StringComparer.OrdinalIgnoreCase)
        {
            "dlq", "api", "db", "sql", "http", "https", "tls", "ssl", "jwt", "id", "ui", "ux", "cli", "ttl", "url", "uri", "s3", "ssh", "rpc", "grpc", "dns", "ip", "tcp", "udp", "cpu", "ram", "wpf", "wsl", "wsl2", "os", "csp", "e2e"
        };

        private readonly UiRequestEnvelope _req;
        private DossierPalette _pal;
        private string _themeMode;
        private readonly List<UiCardItem> _cards;
        private readonly List<UiContractPanel> _panels;
        private readonly Dictionary<string, UiContractPanel> _panelById = new Dictionary<string, UiContractPanel>();
        private readonly string[] _picks;
        private readonly string[] _answers;
        private readonly HashSet<int> _reviewedSteps = new HashSet<int>();
        private readonly List<OptionRowHandle> _optionHandles = new List<OptionRowHandle>();
        private readonly List<TextBlock> _spinePickLabels = new List<TextBlock>();
        private List<FrameworkElement> _spineStepRows = new List<FrameworkElement>();
        private List<string> _spineStepKinds = new List<string>();

        private readonly DispatcherTimer _armTimer;
        private readonly DispatcherTimer _lifeTimer;
        private string _selectedSpecContractId = string.Empty;

        private readonly System.Diagnostics.Stopwatch _idleClock = new System.Diagnostics.Stopwatch();
        private string _ownerVal;
        private string _noteVal = string.Empty;
        private bool _changeRequestOpen;
        private bool _submitting;
        private bool _armed;
        private int _stepIndex;
        private bool _specMode;
        private int _activeTabIndex;

        private Border _dossierOuter;
        private Border _specularRim;
        private Border _readinessHostBorder;
        private Border _rulingChannelBorder;
        private Canvas _rulingCanvas;
        private Border _stageBorder;
        private Border _footerBorder;
        private Border _horizonTrack;
        private Border _horizonFill;
        private ScaleTransform _horizonScale;
        private TextBlock _stageStatusText;
        private Border _modeSegBorder;
        private DossierButton _modeDecideButton;
        private DossierButton _modeSpecButton;
        private Border _spineHostBorder;
        private StackPanel _stageHost;
        private TranslateTransform _stageSlide;
        private ScrollViewer _stageScroll;
        private Grid _stageScrollWrap;
        private Border _specHost;
        private TranslateTransform _specSlide;
        private StackPanel _specContextHost;
        private Grid _tabStripGrid;
        private Border _tabGlideBar;
        private TranslateTransform _tabGlideTransform;
        private StackPanel _specTabBody;
        private TranslateTransform _specBodySlide;
        private ScrollViewer _specScroll;
        private readonly Button[] _tabButtons = new Button[3];
        private readonly TextBlock[] _tabLabels = new TextBlock[3];

        private Ellipse _shockwavePrimary;
        private Ellipse _shockwaveSecondary;
        private ScaleTransform _shockScale1;
        private ScaleTransform _shockScale2;

        private DossierButton _closeButton;
        private DossierButton _themeQuickButton;
        private DossierButton _termButton;
        private DossierButton _moreButton;
        private Popup _morePopup;
        private DossierButton _backButton;
        private DossierButton _primaryButton;

        public UiGestureEnvelope ResultGesture;

        private static bool ResolveLightMode(string themePref)
        {
            string t = (themePref ?? "auto").Trim().ToLowerInvariant();
            if (t == "light") return true;
            if (t == "dark") return false;
            return NativeWin32.IsSystemLightTheme();
        }

        private static bool AllowMotion()
        {
            try { return SystemParameters.ClientAreaAnimation; }
            catch { return true; }
        }

        private static string HumanizeSlug(string raw)
        {
            string s = TextSanitizer.SanitizeText(raw).Trim();
            if (string.IsNullOrEmpty(s)) return "Decision";
            string[] parts = s.Split(new char[] { '-', '_', ' ' }, StringSplitOptions.RemoveEmptyEntries);
            if (parts.Length == 0) return "Decision";
            for (int i = 0; i < parts.Length; i++)
            {
                if (KnownAcronyms.Contains(parts[i])) parts[i] = parts[i].ToUpperInvariant();
                else if (i == 0 && parts[i].Length > 0) parts[i] = char.ToUpperInvariant(parts[i][0]) + parts[i].Substring(1);
            }
            return string.Join(" ", parts);
        }

        private static double? ParseHours(string eff)
        {
            if (string.IsNullOrEmpty(eff)) return null;
            Match m = Regex.Match(eff, @"(\d+(?:\.\d+)?)\s*h", RegexOptions.IgnoreCase);
            if (!m.Success) return null;
            double v;
            if (double.TryParse(m.Groups[1].Value, NumberStyles.Float, CultureInfo.InvariantCulture, out v)) return v;
            return null;
        }

        private ImageSource BuildTaskbarBrandIcon(DossierPalette pal)
        {
            try
            {
                UIElement emb = BuildDriftEmblem(64);
                emb.Measure(new Size(64, 64));
                emb.Arrange(new Rect(0, 0, 64, 64));
                emb.UpdateLayout();
                System.Windows.Media.Imaging.RenderTargetBitmap rtb = new System.Windows.Media.Imaging.RenderTargetBitmap(64, 64, 96, 96, PixelFormats.Pbgra32);
                rtb.Render(emb);
                rtb.Freeze();
                return System.Windows.Media.Imaging.BitmapFrame.Create(rtb);
            }
            catch
            {
                DrawingGroup dg = new DrawingGroup();
                Pen copperPen = new Pen(pal.SpineCopper, 2.1);
                copperPen.Freeze();
                dg.Children.Add(new GeometryDrawing(pal.SpineSolidFallback, copperPen, new RectangleGeometry(new Rect(2, 2, 28, 28), 7, 7)));
                Pen mintPen = new Pen(pal.SpineMint, 2.0);
                mintPen.Freeze();
                RectangleGeometry diamond = new RectangleGeometry(new Rect(9.5, 9.5, 13, 13), 1.5, 1.5);
                diamond.Transform = new RotateTransform(45, 16, 16);
                dg.Children.Add(new GeometryDrawing(DossierPalette.Rgb(18, 42, 38), mintPen, diamond));
                dg.Children.Add(new GeometryDrawing(pal.SpineMintBright, null, new EllipseGeometry(new Point(16, 16), 2.6, 2.6)));
                DrawingImage img = new DrawingImage(dg);
                img.Freeze();
                return img;
            }
        }

        private static void AnimateSlideFade(UIElement target, TranslateTransform slide, double fromX, double fromY, int durationMs)
        {
            if (!AllowMotion()) return;
            CubicEase ease = new CubicEase { EasingMode = EasingMode.EaseOut };
            Duration dur = new Duration(TimeSpan.FromMilliseconds(durationMs));
            target.BeginAnimation(UIElement.OpacityProperty, new DoubleAnimation(0.28, 1.0, dur) { EasingFunction = ease });
            if (slide != null)
            {
                if (Math.Abs(fromX) > 0.1) slide.BeginAnimation(TranslateTransform.XProperty, new DoubleAnimation(fromX, 0.0, dur) { EasingFunction = ease });
                if (Math.Abs(fromY) > 0.1) slide.BeginAnimation(TranslateTransform.YProperty, new DoubleAnimation(fromY, 0.0, dur) { EasingFunction = ease });
            }
        }

        private static void AnimateCascadeItem(UIElement el, int index)
        {
            if (!AllowMotion()) return;
            TranslateTransform tr = new TranslateTransform(0, 0);
            el.RenderTransform = tr;
            QuarticEase ease = new QuarticEase { EasingMode = EasingMode.EaseOut };
            TimeSpan begin = TimeSpan.FromMilliseconds(Math.Min(160, index * 38));
            Duration dur = new Duration(TimeSpan.FromMilliseconds(230));
            el.Opacity = 0.0;
            el.BeginAnimation(UIElement.OpacityProperty, new DoubleAnimation(0.0, 1.0, dur) { BeginTime = begin, EasingFunction = ease });
            tr.BeginAnimation(TranslateTransform.YProperty, new DoubleAnimation(8.0, 0.0, dur) { BeginTime = begin, EasingFunction = ease });
        }

        public DecisionWindow(UiRequestEnvelope req)
        {
            _req = req;
            _themeMode = (req.Theme ?? "auto").Trim().ToLowerInvariant();
            if (_themeMode != "light" && _themeMode != "dark") _themeMode = "auto";
            _pal = DossierPalette.Create(ResolveLightMode(_themeMode));

            _cards = req.Cards != null ? req.Cards : new List<UiCardItem>();
            _panels = req.ContractPanels != null ? req.ContractPanels : new List<UiContractPanel>();
            for (int i = 0; i < _panels.Count; i++)
            {
                UiContractPanel cp = _panels[i];
                if (cp != null && !string.IsNullOrEmpty(cp.Id)) _panelById[cp.Id] = cp;
            }

            _picks = new string[_cards.Count];
            _answers = new string[_cards.Count];
            for (int i = 0; i < _cards.Count; i++)
            {
                _picks[i] = TextSanitizer.SanitizeText(_cards[i].ProposedPick);
                _answers[i] = string.Empty;
            }
            _ownerVal = !string.IsNullOrEmpty(req.Owner)
                ? TextSanitizer.SanitizeText(req.Owner)
                : TextSanitizer.SanitizeText(req.SuggestedOwner);

            _stageSlide = new TranslateTransform(0, 0);
            _specSlide = new TranslateTransform(0, 0);
            _tabGlideTransform = new TranslateTransform(0, 0);
            _specBodySlide = new TranslateTransform(0, 0);

            string projTitle = TextSanitizer.SanitizeText(!string.IsNullOrEmpty(req.ProjectName) ? req.ProjectName : req.AreaName);
            if (string.IsNullOrEmpty(projTitle)) projTitle = "workspace";

            Title = "DRIFT · " + projTitle;
            Icon = BuildTaskbarBrandIcon(_pal);
            Width = 1050;
            Height = 656;
            MinWidth = 790;
            MinHeight = 520;
            WindowStartupLocation = WindowStartupLocation.CenterScreen;
            WindowStyle = WindowStyle.None;
            AllowsTransparency = true;
            Background = Brushes.Transparent;
            ResizeMode = ResizeMode.CanResize;
            Topmost = true;
            UseLayoutRounding = true;
            SnapsToDevicePixels = true;

            ResultGesture = new UiGestureEnvelope
            {
                Schema = "drift.ui-gesture/1",
                RequestId = TextSanitizer.SanitizeText(req.RequestId),
                Action = "cancel",
                ConfirmedReviewRef = string.Empty,
                ConfirmedOwner = string.Empty,
                Note = string.Empty,
                Selections = new List<UiSelectionItem>()
            };

            BuildWindowVisualTree(projTitle);

            int armMs = req.QuietArmMs > 60 ? req.QuietArmMs : 260;
            _armTimer = new DispatcherTimer { Interval = TimeSpan.FromMilliseconds(armMs) };
            _armTimer.Tick += delegate
            {
                _armTimer.Stop();
                _armed = true;
                SyncFooterState();
            };

            int timeoutSec = req.TimeoutSec;
            _lifeTimer = new DispatcherTimer { Interval = TimeSpan.FromMilliseconds(500) };
            _lifeTimer.Tick += delegate
            {
                if (!string.IsNullOrEmpty(_req.SentinelPath) && !File.Exists(_req.SentinelPath))
                {
                    ResultGesture.Action = "parent_gone";
                    Close();
                    return;
                }
                if (timeoutSec > 0 && _idleClock.Elapsed.TotalSeconds >= timeoutSec)
                {
                    ResultGesture.Action = "timeout";
                    Close();
                }
            };

            Loaded += delegate
            {
                Activate();
                Focus();
                RearmGuard();
                _idleClock.Start();
                _lifeTimer.Start();
                UpdateTabGlideIndicator(false);
                RedrawRulingChannel();
                if (AllowMotion())
                {
                    QuinticEase bootEase = new QuinticEase { EasingMode = EasingMode.EaseOut };
                    Duration bootDur = new Duration(TimeSpan.FromMilliseconds(220));
                    ScaleTransform bootScale = new ScaleTransform(0.986, 1.0);
                    TranslateTransform bootTranslate = new TranslateTransform(0.0, 7.0);
                    TransformGroup bootGroup = new TransformGroup();
                    bootGroup.Children.Add(bootScale);
                    bootGroup.Children.Add(bootTranslate);
                    _dossierOuter.RenderTransformOrigin = new Point(0.5, 0.5);
                    _dossierOuter.RenderTransform = bootGroup;
                    _dossierOuter.BeginAnimation(UIElement.OpacityProperty, new DoubleAnimation(0.0, 1.0, bootDur) { EasingFunction = bootEase });
                    bootScale.BeginAnimation(ScaleTransform.ScaleXProperty, new DoubleAnimation(0.986, 1.0, bootDur) { EasingFunction = bootEase });
                    bootScale.BeginAnimation(ScaleTransform.ScaleYProperty, new DoubleAnimation(0.986, 1.0, bootDur) { EasingFunction = bootEase });
                    bootTranslate.BeginAnimation(TranslateTransform.YProperty, new DoubleAnimation(7.0, 0.0, bootDur) { EasingFunction = bootEase });
                }
                Dispatcher.BeginInvoke(DispatcherPriority.Background, new Action(delegate { Topmost = false; }));
            };
            Activated += delegate { RearmGuard(); };
            SizeChanged += delegate { UpdateTabGlideIndicator(false); RedrawRulingChannel(); };
            Closed += delegate
            {
                _armTimer.Stop();
                _lifeTimer.Stop();
            };

            PreviewMouseMove += delegate { _idleClock.Restart(); };
            PreviewMouseDown += delegate { _idleClock.Restart(); };
            PreviewKeyDown += OnWindowPreviewKeyDown;

            SelectSpecTab(0, false);
            RenderAll(false, 0);
        }

        private UIElement BuildUiIcon(string kind, Brush stroke, double size)
        {
            Canvas cv = new Canvas { Width = size, Height = size, VerticalAlignment = VerticalAlignment.Center };
            double s = size / 16.0;
            if (kind == "close")
            {
                cv.Children.Add(new Line { X1 = 3.5 * s, Y1 = 3.5 * s, X2 = 12.5 * s, Y2 = 12.5 * s, Stroke = stroke, StrokeThickness = 1.6, StrokeStartLineCap = PenLineCap.Round, StrokeEndLineCap = PenLineCap.Round });
                cv.Children.Add(new Line { X1 = 12.5 * s, Y1 = 3.5 * s, X2 = 3.5 * s, Y2 = 12.5 * s, Stroke = stroke, StrokeThickness = 1.6, StrokeStartLineCap = PenLineCap.Round, StrokeEndLineCap = PenLineCap.Round });
            }
            else if (kind == "dots")
            {
                double[] xs = new double[] { 3.5, 8.0, 12.5 };
                for (int i = 0; i < 3; i++)
                {
                    Ellipse d = new Ellipse { Width = 2.6 * s, Height = 2.6 * s, Fill = stroke };
                    Canvas.SetLeft(d, (xs[i] - 1.3) * s);
                    Canvas.SetTop(d, 6.7 * s);
                    cv.Children.Add(d);
                }
            }
            else if (kind == "diamond-fill")
            {
                cv.Children.Add(new Polygon
                {
                    Points = new PointCollection { new Point(8 * s, 2 * s), new Point(14 * s, 8 * s), new Point(8 * s, 14 * s), new Point(2 * s, 8 * s) },
                    Fill = stroke
                });
            }
            else if (kind == "diamond-outline")
            {
                cv.Children.Add(new Polygon
                {
                    Points = new PointCollection { new Point(8 * s, 2 * s), new Point(14 * s, 8 * s), new Point(8 * s, 14 * s), new Point(2 * s, 8 * s) },
                    Stroke = stroke,
                    StrokeThickness = 1.4
                });
            }
            else if (kind == "terminal")
            {
                cv.Children.Add(new Polyline
                {
                    Points = new PointCollection { new Point(2.5 * s, 4.5 * s), new Point(6.8 * s, 8.0 * s), new Point(2.5 * s, 11.5 * s) },
                    Stroke = stroke,
                    StrokeThickness = 1.5,
                    StrokeStartLineCap = PenLineCap.Round,
                    StrokeEndLineCap = PenLineCap.Round
                });
                cv.Children.Add(new Line { X1 = 8.2 * s, Y1 = 11.5 * s, X2 = 13.5 * s, Y2 = 11.5 * s, Stroke = stroke, StrokeThickness = 1.5, StrokeStartLineCap = PenLineCap.Round, StrokeEndLineCap = PenLineCap.Round });
            }
            else if (kind == "layers")
            {
                cv.Children.Add(new Polygon
                {
                    Points = new PointCollection { new Point(8 * s, 2.2 * s), new Point(14 * s, 5.6 * s), new Point(8 * s, 9.0 * s), new Point(2 * s, 5.6 * s) },
                    Stroke = stroke,
                    StrokeThickness = 1.3
                });
                cv.Children.Add(new Polyline
                {
                    Points = new PointCollection { new Point(2 * s, 9.4 * s), new Point(8 * s, 12.8 * s), new Point(14 * s, 9.4 * s) },
                    Stroke = stroke,
                    StrokeThickness = 1.3
                });
            }
            else if (kind == "theme")
            {
                Ellipse ring = new Ellipse { Width = 11.2 * s, Height = 11.2 * s, Stroke = stroke, StrokeThickness = 1.35 };
                Canvas.SetLeft(ring, 2.4 * s); Canvas.SetTop(ring, 2.4 * s);
                cv.Children.Add(ring);
                PathFigure pf = new PathFigure { StartPoint = new Point(8 * s, 2.5 * s), IsClosed = true };
                pf.Segments.Add(new ArcSegment(new Point(8 * s, 13.5 * s), new Size(5.5 * s, 5.5 * s), 0, false, SweepDirection.Clockwise, true));
                PathGeometry pg = new PathGeometry();
                pg.Figures.Add(pf);
                cv.Children.Add(new System.Windows.Shapes.Path { Data = pg, Fill = stroke });
            }
            else if (kind == "arrow-left")
            {
                cv.Children.Add(new Line { X1 = 13.0 * s, Y1 = 8.0 * s, X2 = 3.2 * s, Y2 = 8.0 * s, Stroke = stroke, StrokeThickness = 1.5, StrokeStartLineCap = PenLineCap.Round, StrokeEndLineCap = PenLineCap.Round });
                cv.Children.Add(new Polyline { Points = new PointCollection { new Point(7.2 * s, 4.0 * s), new Point(3.0 * s, 8.0 * s), new Point(7.2 * s, 12.0 * s) }, Stroke = stroke, StrokeThickness = 1.5, StrokeStartLineCap = PenLineCap.Round, StrokeEndLineCap = PenLineCap.Round });
            }
            else if (kind == "arrow-right")
            {
                cv.Children.Add(new Line { X1 = 3.0 * s, Y1 = 8.0 * s, X2 = 12.8 * s, Y2 = 8.0 * s, Stroke = stroke, StrokeThickness = 1.5, StrokeStartLineCap = PenLineCap.Round, StrokeEndLineCap = PenLineCap.Round });
                cv.Children.Add(new Polyline { Points = new PointCollection { new Point(8.8 * s, 4.0 * s), new Point(13.0 * s, 8.0 * s), new Point(8.8 * s, 12.0 * s) }, Stroke = stroke, StrokeThickness = 1.5, StrokeStartLineCap = PenLineCap.Round, StrokeEndLineCap = PenLineCap.Round });
            }
            else if (kind == "chevron-right")
            {
                cv.Children.Add(new Polyline { Points = new PointCollection { new Point(5.6 * s, 3.6 * s), new Point(10.4 * s, 8.0 * s), new Point(5.6 * s, 12.4 * s) }, Stroke = stroke, StrokeThickness = 1.5, StrokeStartLineCap = PenLineCap.Round, StrokeEndLineCap = PenLineCap.Round });
            }
            else if (kind == "chevron-down")
            {
                cv.Children.Add(new Polyline { Points = new PointCollection { new Point(3.6 * s, 5.8 * s), new Point(8.0 * s, 10.4 * s), new Point(12.4 * s, 5.8 * s) }, Stroke = stroke, StrokeThickness = 1.5, StrokeStartLineCap = PenLineCap.Round, StrokeEndLineCap = PenLineCap.Round });
            }
            else if (kind == "check")
            {
                cv.Children.Add(new Polyline { Points = new PointCollection { new Point(2.8 * s, 8.4 * s), new Point(6.4 * s, 12.0 * s), new Point(13.4 * s, 4.4 * s) }, Stroke = stroke, StrokeThickness = 1.65, StrokeStartLineCap = PenLineCap.Round, StrokeEndLineCap = PenLineCap.Round });
            }
            else if (kind == "refresh")
            {
                PathFigure pf = new PathFigure { StartPoint = new Point(3.4 * s, 6.2 * s), IsClosed = false };
                pf.Segments.Add(new ArcSegment(new Point(4.2 * s, 11.4 * s), new Size(5.0 * s, 5.0 * s), 0, true, SweepDirection.Clockwise, true));
                PathGeometry pg = new PathGeometry();
                pg.Figures.Add(pf);
                cv.Children.Add(new System.Windows.Shapes.Path { Data = pg, Stroke = stroke, StrokeThickness = 1.4, StrokeStartLineCap = PenLineCap.Round, StrokeEndLineCap = PenLineCap.Round });
                cv.Children.Add(new Polygon { Points = new PointCollection { new Point(2.0 * s, 3.4 * s), new Point(6.4 * s, 4.2 * s), new Point(3.2 * s, 7.6 * s) }, Fill = stroke });
            }
            return cv;
        }

        private UIElement BuildCtaSocket(string gateKind, bool mintVariant)
        {
            Canvas cv = new Canvas { Width = 15, Height = 15, VerticalAlignment = VerticalAlignment.Center };
            Brush gemStroke = mintVariant ? _pal.SpineMintBright : _pal.SpineCopper;
            Brush chevStroke = mintVariant ? _pal.OnMint : _pal.OnCopper;
            if (gateKind == "next" || gateKind == "seal-next")
            {
                cv.Children.Add(new Polygon
                {
                    Points = new PointCollection { new Point(4.4, 4.8), new Point(7.2, 7.6), new Point(4.4, 10.4), new Point(1.6, 7.6) },
                    Fill = mintVariant ? DossierPalette.Rgba(64, 88, 220, 195) : DossierPalette.Rgba(52, 232, 167, 109),
                    Stroke = gateKind == "seal-next" ? _pal.SpineMintBright : gemStroke,
                    StrokeThickness = 1.2
                });
                cv.Children.Add(new Polyline
                {
                    Points = new PointCollection { new Point(8.8, 4.2), new Point(12.5, 7.6), new Point(8.8, 11.0) },
                    Stroke = chevStroke,
                    StrokeThickness = 1.6,
                    StrokeStartLineCap = PenLineCap.Round,
                    StrokeEndLineCap = PenLineCap.Round
                });
            }
            else if (gateKind == "back")
            {
                cv.Children.Add(new Polyline
                {
                    Points = new PointCollection { new Point(6.6, 4.2), new Point(2.9, 7.6), new Point(6.6, 11.0) },
                    Stroke = chevStroke,
                    StrokeThickness = 1.6,
                    StrokeStartLineCap = PenLineCap.Round,
                    StrokeEndLineCap = PenLineCap.Round
                });
                cv.Children.Add(new Polygon
                {
                    Points = new PointCollection { new Point(11.0, 5.0), new Point(13.6, 7.6), new Point(11.0, 10.2), new Point(8.4, 7.6) },
                    Fill = DossierPalette.Rgba(48, 232, 167, 109),
                    Stroke = _pal.SpineCopper,
                    StrokeThickness = 1.15
                });
            }
            else if (gateKind == "approve")
            {
                cv.Children.Add(new Polygon
                {
                    Points = new PointCollection { new Point(7.5, 1.4), new Point(13.6, 7.5), new Point(7.5, 13.6), new Point(1.4, 7.5) },
                    Fill = DossierPalette.Rgba(56, 88, 220, 195),
                    Stroke = _pal.SpineMintBright,
                    StrokeThickness = 1.15
                });
                cv.Children.Add(new Polyline
                {
                    Points = new PointCollection { new Point(4.9, 7.6), new Point(6.8, 9.5), new Point(10.3, 5.7) },
                    Stroke = chevStroke,
                    StrokeThickness = 1.6,
                    StrokeStartLineCap = PenLineCap.Round,
                    StrokeEndLineCap = PenLineCap.Round
                });
            }
            else
            {
                return new Border
                {
                    Width = 23,
                    Height = 23,
                    CornerRadius = new CornerRadius(6),
                    Background = DossierPalette.Rgba(38, 232, 167, 109),
                    BorderBrush = DossierPalette.Rgba(92, 232, 167, 109),
                    BorderThickness = new Thickness(1),
                    Child = BuildUiIcon("refresh", _pal.SpineCopper, 13)
                };
            }
            return new Border
            {
                Width = 23,
                Height = 23,
                CornerRadius = new CornerRadius(6),
                Background = mintVariant ? DossierPalette.Rgba(42, 88, 220, 195) : DossierPalette.Rgba(38, 232, 167, 109),
                BorderBrush = mintVariant ? DossierPalette.Rgba(102, 118, 247, 220) : DossierPalette.Rgba(92, 232, 167, 109),
                BorderThickness = new Thickness(1),
                Child = cv
            };
        }

        private void PrependButtonGlyph(DossierButton db, UIElement glyph, double gap)
        {
            SetButtonIcons(db, glyph, db.Label != null ? db.Label.Text : string.Empty, null, gap);
        }

        private void SetButtonIcons(DossierButton db, UIElement leftIcon, string text, UIElement rightIcon, double gap)
        {
            Grid layers = db.Surface.Child as Grid;
            if (layers == null || db.Label == null) return;
            Thickness pad = (layers.Children.Count > 1 && layers.Children[1] is FrameworkElement)
                ? ((FrameworkElement)layers.Children[1]).Margin
                : db.Label.Margin;
            while (layers.Children.Count > 1) layers.Children.RemoveAt(1);
            Panel oldP = db.Label.Parent as Panel;
            if (oldP != null) oldP.Children.Remove(db.Label);
            db.Label.Text = text ?? string.Empty;
            db.Label.Margin = new Thickness(
                leftIcon != null && !string.IsNullOrEmpty(db.Label.Text) ? gap : 0,
                0,
                rightIcon != null && !string.IsNullOrEmpty(db.Label.Text) ? gap : 0,
                0);
            StackPanel row = new StackPanel
            {
                Orientation = Orientation.Horizontal,
                VerticalAlignment = VerticalAlignment.Center,
                HorizontalAlignment = db.Label.HorizontalAlignment,
                Margin = pad
            };
            if (leftIcon != null) row.Children.Add(leftIcon);
            if (!string.IsNullOrEmpty(db.Label.Text)) row.Children.Add(db.Label);
            if (rightIcon != null) row.Children.Add(rightIcon);
            layers.Children.Add(row);
        }

        private void BuildWindowVisualTree(string projTitle)
        {
            Grid windowHost = new Grid { Margin = new Thickness(18) };

            _dossierOuter = new Border
            {
                CornerRadius = new CornerRadius(13),
                Background = _pal.StageSolidFallback,
                BorderBrush = _pal.OuterRimBrush,
                BorderThickness = new Thickness(1.2),
                SnapsToDevicePixels = true
            };
            TextOptions.SetTextFormattingMode(_dossierOuter, TextFormattingMode.Display);
            TextOptions.SetTextRenderingMode(_dossierOuter, TextRenderingMode.ClearType);
            RenderOptions.SetClearTypeHint(_dossierOuter, ClearTypeHint.Enabled);

            Grid outerLayers = new Grid { ClipToBounds = true };

            Grid shellGrid = new Grid();
            shellGrid.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(280) });
            shellGrid.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(0) });
            shellGrid.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });

            // === COLUMN 0: Atmospheric Living Wave Spine ===
            Border spineBorder = new Border
            {
                CornerRadius = new CornerRadius(12, 0, 0, 12),
                Background = _pal.SpineBgBrush,
                BorderBrush = _pal.SpineBorder,
                BorderThickness = new Thickness(0, 0, 1, 0)
            };

            Grid spineLayers = new Grid();
            spineLayers.Children.Add(new Border
            {
                CornerRadius = new CornerRadius(12, 0, 0, 12),
                Background = _pal.SpineGlowBrush,
                IsHitTestVisible = false
            });
            Grid spineGrid = new Grid { Margin = new Thickness(18, 20, 18, 16) };
            spineGrid.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });
            spineGrid.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });
            spineGrid.RowDefinitions.Add(new RowDefinition { Height = new GridLength(1, GridUnitType.Star) });
            spineGrid.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });

            StackPanel spineTop = new StackPanel();
            Border spineDrag = new Border { Background = Brushes.Transparent, Cursor = Cursors.SizeAll, Padding = new Thickness(0, 0, 0, 10) };
            spineDrag.MouseLeftButtonDown += OnDragBarMouseDown;

            StackPanel brandRow = new StackPanel { Orientation = Orientation.Horizontal, VerticalAlignment = VerticalAlignment.Center };
            UIElement emblem = BuildDriftEmblem(38);
            emblem.SetValue(FrameworkElement.MarginProperty, new Thickness(0, 0, 11, 0));
            brandRow.Children.Add(emblem);

            string wsPath = TextSanitizer.SanitizeText(_req.WorkspacePath);
            TextBlock projText = new TextBlock
            {
                FontFamily = SansFont,
                FontSize = 17,
                FontWeight = FontWeights.ExtraBold,
                Foreground = _pal.SpineInk,
                VerticalAlignment = VerticalAlignment.Center,
                TextTrimming = TextTrimming.CharacterEllipsis,
                MaxWidth = 178,
                ToolTip = !string.IsNullOrEmpty(wsPath) ? wsPath : projTitle,
                Text = projTitle
            };
            brandRow.Children.Add(projText);
            spineDrag.Child = brandRow;
            spineTop.Children.Add(spineDrag);

            StackPanel strataStack = new StackPanel { Margin = new Thickness(0, 0, 0, 10) };
            string branch = TextSanitizer.SanitizeText(_req.GitBranch);
            if (!string.IsNullOrEmpty(branch)) strataStack.Children.Add(MakeStrataPill(BuildBranchGlyph(), branch, wsPath));
            string wt = TextSanitizer.SanitizeText(_req.WorktreeName);
            if (_req.IsLinkedWorktree || (!string.IsNullOrEmpty(wt) && !string.Equals(wt, projTitle, StringComparison.OrdinalIgnoreCase)))
            {
                strataStack.Children.Add(MakeStrataPill(BuildWorktreeGlyph(), "wt:" + wt, wsPath));
            }
            if (strataStack.Children.Count == 0 && !string.IsNullOrEmpty(wsPath)) strataStack.Children.Add(MakeStrataPill(null, wsPath, wsPath));
            spineTop.Children.Add(strataStack);
            Grid.SetRow(spineTop, 0);
            spineGrid.Children.Add(spineTop);

            _readinessHostBorder = new Border { Margin = new Thickness(0, 0, 0, 12) };
            Grid.SetRow(_readinessHostBorder, 1);
            spineGrid.Children.Add(_readinessHostBorder);

            _spineHostBorder = new Border { VerticalAlignment = VerticalAlignment.Stretch };
            Grid.SetRow(_spineHostBorder, 2);
            spineGrid.Children.Add(_spineHostBorder);

            Border ledgerCard = BuildSpineFooterLedger();
            Grid.SetRow(ledgerCard, 3);
            spineGrid.Children.Add(ledgerCard);

            spineLayers.Children.Add(spineGrid);
            spineBorder.Child = spineLayers;
            Grid.SetColumn(spineBorder, 0);
            shellGrid.Children.Add(spineBorder);

            // === COLUMN 1: Collapsed (harmonic wave lives directly inside the Wave Spine) ===
            _rulingCanvas = new Canvas { Width = 36, HorizontalAlignment = HorizontalAlignment.Left, VerticalAlignment = VerticalAlignment.Stretch, IsHitTestVisible = false };
            _rulingChannelBorder = new Border { Width = 0, Visibility = Visibility.Collapsed };
            Grid.SetColumn(_rulingChannelBorder, 1);
            shellGrid.Children.Add(_rulingChannelBorder);

            _stageBorder = new Border
            {
                CornerRadius = new CornerRadius(0, 12, 12, 0),
                Background = _pal.StageBgBrush
            };

            Grid stageLayers = new Grid { ClipToBounds = true };
            stageLayers.Children.Add(BuildSubtleStageChassis());

            Grid stageGrid = new Grid();
            stageGrid.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });
            stageGrid.RowDefinitions.Add(new RowDefinition { Height = new GridLength(1, GridUnitType.Star) });
            stageGrid.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });

            StackPanel topHeaderStack = new StackPanel();
            Border stageTopBar = new Border
            {
                Background = Brushes.Transparent,
                Cursor = Cursors.SizeAll,
                Padding = new Thickness(24, 11, 22, 9)
            };
            stageTopBar.MouseLeftButtonDown += OnDragBarMouseDown;

            StackPanel topLeftControls = new StackPanel { Orientation = Orientation.Horizontal, VerticalAlignment = VerticalAlignment.Center };
            _modeDecideButton = MakeDossierButton("Decision", "Show decision options", _pal.CardIdleBrush, _pal.BtnHover, _pal.CopperBorder, _pal.InkPrimary, new Thickness(12, 4, 12, 4), false, delegate
            {
                if (_specMode) SetSpecMode(false);
            });
            _modeDecideButton.Control.MinHeight = 28;
            _modeDecideButton.Surface.MinHeight = 28;
            _modeDecideButton.Control.Margin = new Thickness(0, 0, 2, 0);

            _modeSpecButton = MakeDossierButton("Apparatus", "Show contract apparatus", Brushes.Transparent, _pal.BtnHover, Brushes.Transparent, _pal.InkBody, new Thickness(12, 4, 12, 4), false, delegate
            {
                if (!_specMode) SetSpecMode(true);
            });
            _modeSpecButton.Control.MinHeight = 28;
            _modeSpecButton.Surface.MinHeight = 28;

            StackPanel segInner = new StackPanel { Orientation = Orientation.Horizontal };
            segInner.Children.Add(_modeDecideButton.Control);
            segInner.Children.Add(_modeSpecButton.Control);
            _modeSegBorder = new Border
            {
                CornerRadius = new CornerRadius(8),
                Background = _pal.WellBg,
                BorderBrush = _pal.BorderSubtle,
                BorderThickness = new Thickness(1),
                Padding = new Thickness(2.5),
                Margin = new Thickness(0, 0, 12, 0),
                Child = segInner
            };

            _stageStatusText = new TextBlock
            {
                FontFamily = MonoFont,
                FontSize = 12,
                FontWeight = FontWeights.Bold,
                Foreground = _pal.InkBody,
                VerticalAlignment = VerticalAlignment.Center
            };
            AutomationProperties.SetLiveSetting(_stageStatusText, AutomationLiveSetting.Polite);
            topLeftControls.Children.Add(_modeSegBorder);
            topLeftControls.Children.Add(_stageStatusText);

            _themeQuickButton = MakeDossierButton(_pal.IsLight ? "Light" : "Dark", "Toggle Dark and Light theme", _pal.WellBg, _pal.BtnHover, _pal.BorderSubtle, _pal.InkBody, new Thickness(10, 4, 10, 4), false, delegate
            {
                bool curLight = ResolveLightMode(_themeMode);
                _themeMode = curLight ? "dark" : "light";
                ApplyPaletteInPlace();
            });
            _themeQuickButton.Label.FontFamily = MonoFont;
            _themeQuickButton.Label.FontSize = 11.5;
            PrependButtonGlyph(_themeQuickButton, BuildUiIcon("theme", _pal.InkBody, 12), 5);
            _themeQuickButton.Control.MinHeight = 28;
            _themeQuickButton.Surface.MinHeight = 28;
            _themeQuickButton.Control.Margin = new Thickness(0, 0, 6, 0);

            _closeButton = MakeDossierButton(string.Empty, "Cancel without changes", Brushes.Transparent, _pal.BtnHover, Brushes.Transparent, _pal.InkMuted, new Thickness(7, 4, 7, 4), false, delegate
            {
                if (_armed) Close();
            });
            PrependButtonGlyph(_closeButton, BuildUiIcon("close", _pal.InkMuted, 13), 0);
            _closeButton.Control.MinHeight = 28;
            _closeButton.Surface.MinHeight = 28;
            _closeButton.Control.ToolTip = "Cancel without changes (Esc)";

            StackPanel topRightControls = new StackPanel { Orientation = Orientation.Horizontal, VerticalAlignment = VerticalAlignment.Center };
            topRightControls.Children.Add(_themeQuickButton.Control);
            topRightControls.Children.Add(_closeButton.Control);
            stageTopBar.Child = MakeSplitRow(topLeftControls, topRightControls, new Thickness(0));
            topHeaderStack.Children.Add(stageTopBar);

            Grid horizonWrap = new Grid { Height = 3, Margin = new Thickness(0, 0, 0, 10) };
            _horizonTrack = new Border
            {
                Height = 3,
                Background = _pal.BorderSubtle,
                VerticalAlignment = VerticalAlignment.Center
            };
            horizonWrap.Children.Add(_horizonTrack);

            _horizonScale = new ScaleTransform(1.0 / Math.Max(1.0, (double)TotalSteps()), 1.0);
            _horizonFill = new Border
            {
                Height = 3,
                Background = _pal.HorizonBeamBrush,
                HorizontalAlignment = HorizontalAlignment.Stretch,
                VerticalAlignment = VerticalAlignment.Center,
                RenderTransformOrigin = new Point(0, 0.5),
                RenderTransform = _horizonScale
            };
            horizonWrap.Children.Add(_horizonFill);
            topHeaderStack.Children.Add(horizonWrap);

            Grid.SetRow(topHeaderStack, 0);
            stageGrid.Children.Add(topHeaderStack);

            Grid bodyHost = new Grid { Margin = new Thickness(24, 2, 24, 10) };
            _stageHost = new StackPanel { RenderTransform = _stageSlide };
            _stageScrollWrap = CreateCleanScrollViewer(_stageHost, new Thickness(0, 0, 4, 2), false, out _stageScroll);
            bodyHost.Children.Add(_stageScrollWrap);

            _specHost = BuildFocusedSpecView(out _specContextHost, out _specTabBody, out _specScroll);
            _specHost.RenderTransform = _specSlide;
            _specHost.Visibility = Visibility.Collapsed;
            bodyHost.Children.Add(_specHost);

            Grid.SetRow(bodyHost, 1);
            stageGrid.Children.Add(bodyHost);

            _footerBorder = new Border
            {
                BorderBrush = _pal.BorderCard,
                BorderThickness = new Thickness(0, 1.5, 0, 0),
                Padding = new Thickness(24, 11, 24, 13)
            };

            StackPanel leftFoot = new StackPanel { Orientation = Orientation.Horizontal, VerticalAlignment = VerticalAlignment.Center };
            _termButton = MakeDossierButton("CLI", "Use terminal for this review only", _pal.WellBg, _pal.BtnHover, _pal.BorderSubtle, _pal.InkBody, new Thickness(12, 7, 12, 7), true, delegate
            {
                if (_submitting) return;
                _submitting = true;
                ResultGesture.Action = "use_terminal_once";
                Close();
            });
            _termButton.Label.FontFamily = MonoFont;
            _termButton.Label.FontSize = 12;
            PrependButtonGlyph(_termButton, BuildUiIcon("terminal", _pal.Mint, 13), 6);
            _termButton.Control.ToolTip = "Return to terminal for this review (keeps desktop UI enabled)";
            _termButton.Control.Margin = new Thickness(0, 0, 8, 0);
            leftFoot.Children.Add(_termButton.Control);

            _moreButton = MakeDossierButton(string.Empty, "Theme and CLI preferences", _pal.WellBg, _pal.BtnHover, _pal.BorderSubtle, _pal.InkMuted, new Thickness(10, 7, 10, 7), false, null);
            PrependButtonGlyph(_moreButton, BuildUiIcon("dots", _pal.InkMuted, 14), 0);
            _morePopup = BuildMorePopup();
            _moreButton.Control.Click += delegate
            {
                _morePopup.IsOpen = !_morePopup.IsOpen;
            };
            leftFoot.Children.Add(_moreButton.Control);

            StackPanel rightFoot = new StackPanel { Orientation = Orientation.Horizontal, VerticalAlignment = VerticalAlignment.Center };
            _backButton = MakeDossierButton("Back", "Previous step", _pal.WellBg, _pal.BtnHover, _pal.BorderSubtle, _pal.InkBody, new Thickness(14, 7, 14, 7), true, delegate
            {
                if (_specMode) { SetSpecMode(false); return; }
                Navigate(-1);
            });
            PrependButtonGlyph(_backButton, BuildUiIcon("arrow-left", _pal.InkBody, 12.5), 6);
            _backButton.Control.Margin = new Thickness(0, 0, 8, 0);
            rightFoot.Children.Add(_backButton.Control);

            _primaryButton = MakeDossierButton("Continue", "Primary action", _pal.CopperCtaBrush, _pal.CopperCtaHoverBrush, _pal.OuterRimBrush, _pal.OnCopper, new Thickness(15, 5.5, 7, 5.5), true, delegate
            {
                if (_specMode) { SetSpecMode(false); return; }
                OnPrimaryAction(true);
            });
            _primaryButton.Surface.CornerRadius = new CornerRadius(10);
            _primaryButton.Surface.BorderThickness = new Thickness(1.1);
            _primaryButton.Surface.MinHeight = 36;
            _primaryButton.Label.FontWeight = FontWeights.Bold;
            rightFoot.Children.Add(_primaryButton.Control);

            _footerBorder.Child = MakeSplitRow(leftFoot, rightFoot, new Thickness(0));
            Grid.SetRow(_footerBorder, 2);
            stageGrid.Children.Add(_footerBorder);

            stageLayers.Children.Add(stageGrid);

            Canvas grip = new Canvas
            {
                Width = 13,
                Height = 13,
                HorizontalAlignment = HorizontalAlignment.Right,
                VerticalAlignment = VerticalAlignment.Bottom,
                Margin = new Thickness(0, 0, 7, 7),
                Cursor = Cursors.SizeNWSE,
                Background = Brushes.Transparent
            };
            grip.Children.Add(new Line { X1 = 11, Y1 = 3, X2 = 3, Y2 = 11, Stroke = _pal.CopperBorder, StrokeThickness = 1.1, Opacity = 0.7 });
            grip.Children.Add(new Line { X1 = 11, Y1 = 7, X2 = 7, Y2 = 11, Stroke = _pal.MintBorder, StrokeThickness = 1.1, Opacity = 0.7 });
            grip.MouseLeftButtonDown += delegate(object s, MouseButtonEventArgs ev)
            {
                ev.Handled = true;
                IntPtr hwnd = new WindowInteropHelper(this).Handle;
                if (hwnd != IntPtr.Zero)
                {
                    NativeWin32.ReleaseCapture();
                    NativeWin32.SendMessage(hwnd, 0x0112, (IntPtr)(0xF000 + 8), IntPtr.Zero);
                }
            };
            stageLayers.Children.Add(grip);

            _stageBorder.Child = stageLayers;
            Grid.SetColumn(_stageBorder, 2);
            shellGrid.Children.Add(_stageBorder);

            outerLayers.Children.Add(shellGrid);

            _specularRim = new Border
            {
                Height = 1,
                Margin = new Thickness(6, 1, 6, 0),
                VerticalAlignment = VerticalAlignment.Top,
                Background = _pal.InnerSpecularRim,
                IsHitTestVisible = false
            };
            outerLayers.Children.Add(_specularRim);

            _dossierOuter.Child = outerLayers;
            windowHost.Children.Add(_dossierOuter);

            // 8-direction perimeter resize handles
            windowHost.Children.Add(MakeResizeZone(Cursors.SizeWE, 1, HorizontalAlignment.Left, VerticalAlignment.Stretch, 10, double.NaN, new Thickness(12, 26, 0, 26)));
            windowHost.Children.Add(MakeResizeZone(Cursors.SizeWE, 2, HorizontalAlignment.Right, VerticalAlignment.Stretch, 10, double.NaN, new Thickness(0, 26, 12, 26)));
            windowHost.Children.Add(MakeResizeZone(Cursors.SizeNS, 3, HorizontalAlignment.Stretch, VerticalAlignment.Top, double.NaN, 10, new Thickness(26, 12, 26, 0)));
            windowHost.Children.Add(MakeResizeZone(Cursors.SizeNS, 6, HorizontalAlignment.Stretch, VerticalAlignment.Bottom, double.NaN, 10, new Thickness(26, 0, 26, 12)));
            windowHost.Children.Add(MakeResizeZone(Cursors.SizeNWSE, 4, HorizontalAlignment.Left, VerticalAlignment.Top, 16, 16, new Thickness(10, 10, 0, 0)));
            windowHost.Children.Add(MakeResizeZone(Cursors.SizeNESW, 5, HorizontalAlignment.Right, VerticalAlignment.Top, 16, 16, new Thickness(0, 10, 10, 0)));
            windowHost.Children.Add(MakeResizeZone(Cursors.SizeNESW, 7, HorizontalAlignment.Left, VerticalAlignment.Bottom, 16, 16, new Thickness(10, 0, 0, 10)));
            windowHost.Children.Add(MakeResizeZone(Cursors.SizeNWSE, 8, HorizontalAlignment.Right, VerticalAlignment.Bottom, 18, 18, new Thickness(0, 0, 10, 10)));

            Content = windowHost;
        }

        private UIElement BuildSubtleStageChassis()
        {
            Grid overlay = new Grid { IsHitTestVisible = false, Margin = new Thickness(8) };

            // Living rotating observatory astrolabe watermark anchored cleanly below header
            Canvas astro = new Canvas
            {
                Width = 148,
                Height = 148,
                HorizontalAlignment = HorizontalAlignment.Right,
                VerticalAlignment = VerticalAlignment.Top,
                Margin = new Thickness(0, 44, 10, 0),
                Opacity = _pal.IsLight ? 0.065 : 0.08
            };
            RotateTransform rotOuter = new RotateTransform(0, 66, 66);
            Ellipse rOuter = new Ellipse { Width = 132, Height = 132, Stroke = _pal.Copper, StrokeThickness = 1.0, StrokeDashArray = new DoubleCollection(new double[] { 4, 8 }), RenderTransform = rotOuter };
            Canvas.SetLeft(rOuter, 8); Canvas.SetTop(rOuter, 8);
            astro.Children.Add(rOuter);

            RotateTransform rotInner = new RotateTransform(0, 46, 46);
            Ellipse rInner = new Ellipse { Width = 92, Height = 92, Stroke = _pal.Mint, StrokeThickness = 0.9, StrokeDashArray = new DoubleCollection(new double[] { 2, 7 }), RenderTransform = rotInner };
            Canvas.SetLeft(rInner, 28); Canvas.SetTop(rInner, 28);
            astro.Children.Add(rInner);

            if (AllowMotion())
            {
                rotOuter.BeginAnimation(RotateTransform.AngleProperty, new DoubleAnimation(0, 360, new Duration(TimeSpan.FromSeconds(54))) { RepeatBehavior = RepeatBehavior.Forever });
                rotInner.BeginAnimation(RotateTransform.AngleProperty, new DoubleAnimation(360, 0, new Duration(TimeSpan.FromSeconds(72))) { RepeatBehavior = RepeatBehavior.Forever });
            }

            Rectangle rotSq = new Rectangle
            {
                Width = 60,
                Height = 60,
                Stroke = _pal.Copper,
                StrokeThickness = 0.9,
                RenderTransform = new RotateTransform(45, 30, 30)
            };
            Canvas.SetLeft(rotSq, 44); Canvas.SetTop(rotSq, 44);
            astro.Children.Add(rotSq);
            overlay.Children.Add(astro);

            // Fine engraved corner calibration ticks on stage
            overlay.Children.Add(MakeFineCornerBracket(HorizontalAlignment.Right, VerticalAlignment.Top, _pal.Copper, true, false));
            overlay.Children.Add(MakeFineCornerBracket(HorizontalAlignment.Right, VerticalAlignment.Bottom, _pal.Mint, true, true));
            return overlay;
        }

        private static UIElement MakeFineCornerBracket(HorizontalAlignment ha, VerticalAlignment va, Brush stroke, bool flipX, bool flipY)
        {
            Canvas c = new Canvas { Width = 14, Height = 14, HorizontalAlignment = ha, VerticalAlignment = va, Opacity = 0.42 };
            double x0 = flipX ? 13 : 1;
            double xArm = flipX ? 4 : 10;
            double y0 = flipY ? 13 : 1;
            double yArm = flipY ? 4 : 10;
            c.Children.Add(new Line { X1 = x0, Y1 = y0, X2 = xArm, Y2 = y0, Stroke = stroke, StrokeThickness = 1.3 });
            c.Children.Add(new Line { X1 = x0, Y1 = y0, X2 = x0, Y2 = yArm, Stroke = stroke, StrokeThickness = 1.3 });
            return c;
        }

        private void OnDragBarMouseDown(object sender, MouseButtonEventArgs ev)
        {
            if (ev.ClickCount == 2)
            {
                ToggleSpecMode();
                ev.Handled = true;
                return;
            }
            if (ev.ButtonState == MouseButtonState.Pressed)
            {
                try { DragMove(); } catch { }
            }
        }

        private Border MakePopupRow(string iconKind, Brush glyphColor, string label, Action onPick)
        {
            Grid g = new Grid();
            g.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(24) });
            g.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
            AddCell(g, 0, new Border
            {
                VerticalAlignment = VerticalAlignment.Center,
                HorizontalAlignment = HorizontalAlignment.Left,
                Child = BuildUiIcon(iconKind, glyphColor, 13)
            });
            AddCell(g, 1, new TextBlock
            {
                FontFamily = SansFont,
                FontSize = 13,
                FontWeight = FontWeights.Medium,
                Foreground = _pal.InkPrimary,
                VerticalAlignment = VerticalAlignment.Center,
                Text = label
            });
            Border b = new Border
            {
                CornerRadius = new CornerRadius(7),
                Background = Brushes.Transparent,
                Padding = new Thickness(10, 8, 12, 8),
                Cursor = Cursors.Hand,
                Child = g
            };
            b.MouseEnter += delegate { b.Background = _pal.BtnHover; };
            b.MouseLeave += delegate { b.Background = Brushes.Transparent; };
            b.MouseLeftButtonUp += delegate(object s, MouseButtonEventArgs ev)
            {
                ev.Handled = true;
                if (_morePopup != null) _morePopup.IsOpen = false;
                if (onPick != null) onPick();
            };
            return b;
        }

        private Popup BuildMorePopup()
        {
            Popup pop = new Popup
            {
                AllowsTransparency = true,
                PlacementTarget = _moreButton.Control,
                Placement = PlacementMode.Top,
                VerticalOffset = -6,
                HorizontalOffset = -90,
                StaysOpen = false,
                PopupAnimation = PopupAnimation.Fade
            };

            Grid wrap = new Grid { Margin = new Thickness(10) };

            StackPanel items = new StackPanel();
            items.Children.Add(MakePopupRow("theme", _pal.Copper, _themeMode == "auto" ? "Lock theme (Dark / Light)" : "Reset theme to Auto", delegate
            {
                _themeMode = _themeMode == "auto" ? (_pal.IsLight ? "dark" : "light") : "auto";
                ApplyPaletteInPlace();
            }));
            items.Children.Add(MakePopupRow("terminal", _pal.Mint, "Always use CLI (disable popups)", delegate
            {
                if (_submitting) return;
                _submitting = true;
                ResultGesture.Action = "disable_ui";
                Close();
            }));
            items.Children.Add(new Border { Height = 1, Background = _pal.BorderSubtle, Margin = new Thickness(8, 5, 8, 6) });
            items.Children.Add(new TextBlock
            {
                FontFamily = MonoFont,
                FontSize = 11.5,
                Foreground = _pal.InkMuted,
                Margin = new Thickness(10, 2, 12, 6),
                Text = "1-9 select · Space apparatus · Tab switch · Ctrl+Enter seal · Esc"
            });

            Border card = new Border
            {
                CornerRadius = new CornerRadius(10),
                Background = _pal.CardIdleBrush,
                BorderBrush = _pal.BorderSubtle,
                BorderThickness = new Thickness(1.0),
                Padding = new Thickness(6),
                SnapsToDevicePixels = true,
                Child = items
            };
            TextOptions.SetTextFormattingMode(card, TextFormattingMode.Display);
            TextOptions.SetTextRenderingMode(card, TextRenderingMode.ClearType);
            RenderOptions.SetClearTypeHint(card, ClearTypeHint.Enabled);
            wrap.Children.Add(card);

            pop.Child = wrap;
            return pop;
        }

        private void SyncModeButtons()
        {
            if (_modeSegBorder != null)
            {
                _modeSegBorder.Background = _pal.WellBg;
                _modeSegBorder.BorderBrush = _pal.BorderSubtle;
            }
            if (_modeDecideButton != null)
            {
                _modeDecideButton.NormalBg = !_specMode ? _pal.CardIdleBrush : Brushes.Transparent;
                _modeDecideButton.NormalBorder = !_specMode ? _pal.CopperBorder : Brushes.Transparent;
                _modeDecideButton.NormalFg = !_specMode ? _pal.InkPrimary : _pal.InkBody;
                _modeDecideButton.SyncVisual(false, false);
            }
            if (_modeSpecButton != null)
            {
                _modeSpecButton.NormalBg = _specMode ? _pal.CardIdleBrush : Brushes.Transparent;
                _modeSpecButton.NormalBorder = _specMode ? _pal.CopperBorder : Brushes.Transparent;
                _modeSpecButton.NormalFg = _specMode ? _pal.InkPrimary : _pal.InkBody;
                _modeSpecButton.SyncVisual(false, false);
            }
        }

        private void ApplyPaletteInPlace()
        {
            _pal = DossierPalette.Create(ResolveLightMode(_themeMode));
            _dossierOuter.Background = _pal.StageSolidFallback;
            _dossierOuter.BorderBrush = _pal.OuterRimBrush;
            _specularRim.Background = _pal.InnerSpecularRim;
            if (_rulingChannelBorder != null)
            {
                _rulingChannelBorder.Background = _pal.IsLight ? DossierPalette.Rgb(232, 225, 210) : DossierPalette.Rgb(17, 21, 29);
                _rulingChannelBorder.BorderBrush = _pal.BorderCard;
            }
            _stageBorder.Background = _pal.StageBgBrush;
            _footerBorder.BorderBrush = _pal.BorderCard;
            _horizonTrack.Background = _pal.BorderSubtle;
            _stageStatusText.Foreground = _pal.InkBody;

            DossierButton[] wellBtns = new DossierButton[] { _termButton, _moreButton, _backButton, _themeQuickButton };
            for (int i = 0; i < wellBtns.Length; i++)
            {
                if (wellBtns[i] == null) continue;
                wellBtns[i].NormalBg = _pal.WellBg;
                wellBtns[i].HoverBg = _pal.BtnHover;
                wellBtns[i].NormalBorder = _pal.BorderSubtle;
                wellBtns[i].FocusBorder = _pal.CopperStroke;
                wellBtns[i].NormalFg = (wellBtns[i] == _moreButton) ? _pal.InkMuted : _pal.InkBody;
                wellBtns[i].SyncVisual(false, false);
            }
            SetButtonIcons(_termButton, BuildUiIcon("terminal", _pal.Mint, 13), "CLI", null, 6);
            SetButtonIcons(_moreButton, BuildUiIcon("dots", _pal.InkMuted, 14), string.Empty, null, 0);
            SetButtonIcons(_themeQuickButton, BuildUiIcon("theme", _pal.InkBody, 12), _pal.IsLight ? "Light" : "Dark", null, 5);
            _closeButton.NormalBg = Brushes.Transparent;
            _closeButton.HoverBg = _pal.BtnHover;
            _closeButton.NormalBorder = Brushes.Transparent;
            _closeButton.NormalFg = _pal.InkMuted;
            _closeButton.FocusBorder = _pal.CopperStroke;
            SetButtonIcons(_closeButton, BuildUiIcon("close", _pal.InkMuted, 13), string.Empty, null, 0);
            _closeButton.SyncVisual(false, false);
            SyncModeButtons();

            if (_morePopup != null) _morePopup.IsOpen = false;
            _morePopup = BuildMorePopup();

            SelectSpecTab(_activeTabIndex, false);
            RenderAll(false, 0);
        }

        // === Full Animated Observatory Gate Logo from assets/logo.svg (512x512 Viewbox) ===
        private UIElement BuildDriftEmblem(double size)
        {
            Canvas c = new Canvas { Width = 512, Height = 512 };

            RadialGradientBrush boardBg = new RadialGradientBrush
            {
                Center = new Point(0.5, 0.46),
                GradientOrigin = new Point(0.5, 0.46),
                RadiusX = 0.70,
                RadiusY = 0.70
            };
            boardBg.GradientStops.Add(new GradientStop(Color.FromRgb(30, 35, 40), 0.0));
            boardBg.GradientStops.Add(new GradientStop(Color.FromRgb(24, 27, 31), 0.65));
            boardBg.GradientStops.Add(new GradientStop(Color.FromRgb(18, 21, 24), 1.0));
            boardBg.Freeze();

            LinearGradientBrush copperFrame = new LinearGradientBrush { StartPoint = new Point(0, 0), EndPoint = new Point(1, 1) };
            copperFrame.GradientStops.Add(new GradientStop(Color.FromArgb(218, 232, 167, 109), 0.0));
            copperFrame.GradientStops.Add(new GradientStop(Color.FromArgb(145, 203, 147, 103), 0.5));
            copperFrame.GradientStops.Add(new GradientStop(Color.FromArgb(195, 88, 220, 195), 1.0));
            copperFrame.Freeze();

            Rectangle outerSq = new Rectangle
            {
                Width = 472,
                Height = 472,
                RadiusX = 96,
                RadiusY = 96,
                Fill = boardBg,
                Stroke = copperFrame,
                StrokeThickness = 11.0
            };
            Canvas.SetLeft(outerSq, 20); Canvas.SetTop(outerSq, 20);
            c.Children.Add(outerSq);

            Rectangle innerRim = new Rectangle
            {
                Width = 432,
                Height = 432,
                RadiusX = 78,
                RadiusY = 78,
                Stroke = DossierPalette.Rgb(56, 59, 61),
                StrokeThickness = 6.0
            };
            Canvas.SetLeft(innerRim, 40); Canvas.SetTop(innerRim, 40);
            c.Children.Add(innerRim);

            RadialGradientBrush fluxGlow = new RadialGradientBrush();
            fluxGlow.GradientStops.Add(new GradientStop(Color.FromArgb(62, 88, 220, 195), 0.0));
            fluxGlow.GradientStops.Add(new GradientStop(Color.FromArgb(20, 88, 220, 195), 0.55));
            fluxGlow.GradientStops.Add(new GradientStop(Color.FromArgb(0, 88, 220, 195), 1.0));
            fluxGlow.Freeze();

            Ellipse glowCircle = new Ellipse { Width = 392, Height = 392, Fill = fluxGlow };
            Canvas.SetLeft(glowCircle, 60); Canvas.SetTop(glowCircle, 60);
            if (AllowMotion())
            {
                glowCircle.BeginAnimation(UIElement.OpacityProperty, new DoubleAnimation(0.75, 1.0, new Duration(TimeSpan.FromSeconds(3.8)))
                {
                    AutoReverse = true,
                    RepeatBehavior = RepeatBehavior.Forever,
                    EasingFunction = new SineEase { EasingMode = EasingMode.EaseInOut }
                });
            }
            c.Children.Add(glowCircle);

            // Cartographic axes
            c.Children.Add(new Line { X1 = 52, Y1 = 256, X2 = 460, Y2 = 256, Stroke = DossierPalette.Rgba(85, 154, 152, 145), StrokeThickness = 5.0, StrokeDashArray = new DoubleCollection(new double[] { 3, 5 }) });
            c.Children.Add(new Line { X1 = 256, Y1 = 52, X2 = 256, Y2 = 460, Stroke = DossierPalette.Rgba(85, 154, 152, 145), StrokeThickness = 5.0, StrokeDashArray = new DoubleCollection(new double[] { 3, 5 }) });

            // Left Copper signal wave + flowing pulse
            Geometry leftWaveGeo = Geometry.Parse("M 66,256 C 106,256 122,198 152,216 C 176,230 178,256 194,256");
            c.Children.Add(new System.Windows.Shapes.Path { Data = leftWaveGeo, Stroke = _pal.SpineCopper, StrokeThickness = 14.0, StrokeStartLineCap = PenLineCap.Round, StrokeEndLineCap = PenLineCap.Round, Opacity = 0.90 });
            System.Windows.Shapes.Path leftPulse = new System.Windows.Shapes.Path
            {
                Data = leftWaveGeo,
                Stroke = DossierPalette.Rgb(255, 206, 139),
                StrokeThickness = 17.0,
                StrokeDashArray = new DoubleCollection(new double[] { 1.8, 5.2 }),
                StrokeStartLineCap = PenLineCap.Round,
                StrokeEndLineCap = PenLineCap.Round
            };
            c.Children.Add(leftPulse);

            // Right Verdigris proof wave + flowing pulse
            Geometry rightWaveGeo = Geometry.Parse("M 318,256 C 336,256 352,200 380,218 C 406,234 418,256 446,256");
            c.Children.Add(new System.Windows.Shapes.Path { Data = rightWaveGeo, Stroke = _pal.SpineMint, StrokeThickness = 14.0, StrokeStartLineCap = PenLineCap.Round, StrokeEndLineCap = PenLineCap.Round, Opacity = 0.92 });
            System.Windows.Shapes.Path rightPulse = new System.Windows.Shapes.Path
            {
                Data = rightWaveGeo,
                Stroke = DossierPalette.Rgb(116, 255, 228),
                StrokeThickness = 17.0,
                StrokeDashArray = new DoubleCollection(new double[] { 1.8, 5.2 }),
                StrokeStartLineCap = PenLineCap.Round,
                StrokeEndLineCap = PenLineCap.Round
            };
            c.Children.Add(rightPulse);

            if (AllowMotion())
            {
                DoubleAnimation waveFlow = new DoubleAnimation(14.0, 0.0, new Duration(TimeSpan.FromSeconds(2.4))) { RepeatBehavior = RepeatBehavior.Forever };
                leftPulse.BeginAnimation(Shape.StrokeDashOffsetProperty, waveFlow);
                rightPulse.BeginAnimation(Shape.StrokeDashOffsetProperty, waveFlow);
            }

            // Rotating outer satellite orbit (r = 166)
            Canvas orbitGroup = new Canvas { Width = 512, Height = 512, RenderTransformOrigin = new Point(0.5, 0.5) };
            RotateTransform orbitRot = new RotateTransform(0);
            orbitGroup.RenderTransform = orbitRot;
            Ellipse satRing = new Ellipse
            {
                Width = 332,
                Height = 332,
                Stroke = DossierPalette.Rgba(165, 122, 135, 126),
                StrokeThickness = 8.0,
                StrokeDashArray = new DoubleCollection(new double[] { 2.0, 4.5 })
            };
            Canvas.SetLeft(satRing, 90); Canvas.SetTop(satRing, 90);
            orbitGroup.Children.Add(satRing);

            Ellipse satCopper = new Ellipse { Width = 28, Height = 28, Fill = _pal.SpineCopper };
            Canvas.SetLeft(satCopper, 242); Canvas.SetTop(satCopper, 76);
            orbitGroup.Children.Add(satCopper);

            Ellipse satMint = new Ellipse { Width = 24, Height = 24, Fill = _pal.SpineMintBright };
            Canvas.SetLeft(satMint, 362); Canvas.SetTop(satMint, 362);
            orbitGroup.Children.Add(satMint);

            if (AllowMotion())
            {
                orbitRot.BeginAnimation(RotateTransform.AngleProperty, new DoubleAnimation(0.0, 360.0, new Duration(TimeSpan.FromSeconds(24.0)))
                {
                    RepeatBehavior = RepeatBehavior.Forever
                });
            }
            c.Children.Add(orbitGroup);

            // Concentric copper & sage calibration rings + 4 cardinal ticks
            Ellipse cRing = new Ellipse { Width = 248, Height = 248, Stroke = DossierPalette.Rgba(175, 188, 129, 81), StrokeThickness = 9.0 };
            Canvas.SetLeft(cRing, 132); Canvas.SetTop(cRing, 132);
            c.Children.Add(cRing);

            c.Children.Add(new Line { X1 = 256, Y1 = 114, X2 = 256, Y2 = 138, Stroke = _pal.SpineCopper, StrokeThickness = 12.0, StrokeStartLineCap = PenLineCap.Round, StrokeEndLineCap = PenLineCap.Round });
            c.Children.Add(new Line { X1 = 256, Y1 = 374, X2 = 256, Y2 = 398, Stroke = _pal.SpineCopper, StrokeThickness = 12.0, StrokeStartLineCap = PenLineCap.Round, StrokeEndLineCap = PenLineCap.Round });
            c.Children.Add(new Line { X1 = 114, Y1 = 256, X2 = 138, Y2 = 256, Stroke = _pal.SpineCopper, StrokeThickness = 12.0, StrokeStartLineCap = PenLineCap.Round, StrokeEndLineCap = PenLineCap.Round });
            c.Children.Add(new Line { X1 = 374, Y1 = 256, X2 = 398, Y2 = 256, Stroke = _pal.SpineCopper, StrokeThickness = 12.0, StrokeStartLineCap = PenLineCap.Round, StrokeEndLineCap = PenLineCap.Round });

            // Double-nested 45° rotated diamonds
            Rectangle outerDiamond = new Rectangle
            {
                Width = 148,
                Height = 148,
                RadiusX = 12,
                RadiusY = 12,
                Fill = DossierPalette.Rgb(25, 34, 32),
                Stroke = DossierPalette.Rgb(203, 147, 103),
                StrokeThickness = 15.0,
                RenderTransform = new RotateTransform(45, 74, 74)
            };
            Canvas.SetLeft(outerDiamond, 182); Canvas.SetTop(outerDiamond, 182);
            c.Children.Add(outerDiamond);

            Rectangle innerDiamond = new Rectangle
            {
                Width = 100,
                Height = 100,
                RadiusX = 9,
                RadiusY = 9,
                Fill = DossierPalette.Rgb(16, 41, 38),
                Stroke = _pal.SpineMint,
                StrokeThickness = 16.0,
                RenderTransform = new RotateTransform(45, 50, 50)
            };
            Canvas.SetLeft(innerDiamond, 206); Canvas.SetTop(innerDiamond, 206);
            c.Children.Add(innerDiamond);

            // Breathing central core node
            ScaleTransform corePulse = new ScaleTransform(1.0, 1.0);
            Ellipse core = new Ellipse
            {
                Width = 36,
                Height = 36,
                Fill = _pal.SpineMintBright,
                RenderTransformOrigin = new Point(0.5, 0.5),
                RenderTransform = corePulse
            };
            Canvas.SetLeft(core, 238); Canvas.SetTop(core, 238);
            if (AllowMotion())
            {
                DoubleAnimation breathe = new DoubleAnimation(0.84, 1.14, new Duration(TimeSpan.FromSeconds(2.6)))
                {
                    AutoReverse = true,
                    RepeatBehavior = RepeatBehavior.Forever,
                    EasingFunction = new SineEase { EasingMode = EasingMode.EaseInOut }
                };
                corePulse.BeginAnimation(ScaleTransform.ScaleXProperty, breathe);
                corePulse.BeginAnimation(ScaleTransform.ScaleYProperty, breathe);
            }
            c.Children.Add(core);

            Ellipse pupil = new Ellipse { Width = 12, Height = 12, Fill = DossierPalette.Rgb(28, 88, 78) };
            Canvas.SetLeft(pupil, 250); Canvas.SetTop(pupil, 250);
            c.Children.Add(pupil);

            return new Viewbox { Width = size, Height = size, Child = c };
        }

        private UIElement BuildBranchGlyph()
        {
            Canvas c = new Canvas { Width = 12, Height = 12, Margin = new Thickness(0, 0, 7, 0), VerticalAlignment = VerticalAlignment.Center };
            Ellipse top = new Ellipse { Width = 3.4, Height = 3.4, Stroke = _pal.SpineCopper, StrokeThickness = 1.2 };
            Canvas.SetLeft(top, 1.8); Canvas.SetTop(top, 1.2);
            Ellipse bot = new Ellipse { Width = 3.4, Height = 3.4, Stroke = _pal.SpineCopper, StrokeThickness = 1.2 };
            Canvas.SetLeft(bot, 1.8); Canvas.SetTop(bot, 7.4);
            Ellipse br = new Ellipse { Width = 3.4, Height = 3.4, Stroke = _pal.SpineCopper, StrokeThickness = 1.2 };
            Canvas.SetLeft(br, 6.8); Canvas.SetTop(br, 3.0);
            c.Children.Add(new Line { X1 = 3.5, Y1 = 4.6, X2 = 3.5, Y2 = 7.4, Stroke = _pal.SpineCopper, StrokeThickness = 1.2 });
            c.Children.Add(new Line { X1 = 8.5, Y1 = 6.2, X2 = 3.8, Y2 = 7.8, Stroke = _pal.SpineCopper, StrokeThickness = 1.1 });
            c.Children.Add(top); c.Children.Add(bot); c.Children.Add(br);
            return c;
        }

        private UIElement BuildWorktreeGlyph()
        {
            Canvas c = new Canvas { Width = 12, Height = 12, Margin = new Thickness(0, 0, 7, 0), VerticalAlignment = VerticalAlignment.Center };
            Rectangle r1 = new Rectangle { Width = 5.6, Height = 5.6, Stroke = _pal.SpineMint, StrokeThickness = 1.15, RenderTransform = new RotateTransform(45, 2.8, 2.8) };
            Canvas.SetLeft(r1, 1.2); Canvas.SetTop(r1, 3.2);
            Rectangle r2 = new Rectangle { Width = 5.6, Height = 5.6, Fill = _pal.SpineWell, Stroke = _pal.SpineMintBright, StrokeThickness = 1.15, RenderTransform = new RotateTransform(45, 2.8, 2.8) };
            Canvas.SetLeft(r2, 4.8); Canvas.SetTop(r2, 3.2);
            c.Children.Add(r1); c.Children.Add(r2);
            return c;
        }

        private UIElement BuildStepDiamond(string kind)
        {
            Canvas c = new Canvas { Width = 22, Height = 22, VerticalAlignment = VerticalAlignment.Top, Margin = new Thickness(0, 1, 0, 0) };
            if (kind == "active")
            {
                ScaleTransform ringPulse = new ScaleTransform(1.0, 1.0);
                Polygon aura = new Polygon
                {
                    Points = new PointCollection { new Point(11, 0.8), new Point(21.2, 11), new Point(11, 21.2), new Point(0.8, 11) },
                    Stroke = _pal.SpineCopper,
                    StrokeThickness = 1.0,
                    Opacity = 0.45,
                    RenderTransformOrigin = new Point(0.5, 0.5),
                    RenderTransform = ringPulse
                };
                if (AllowMotion())
                {
                    DoubleAnimation rp = new DoubleAnimation(0.92, 1.18, new Duration(TimeSpan.FromSeconds(1.9)))
                    {
                        AutoReverse = true,
                        RepeatBehavior = RepeatBehavior.Forever,
                        EasingFunction = new SineEase { EasingMode = EasingMode.EaseInOut }
                    };
                    ringPulse.BeginAnimation(ScaleTransform.ScaleXProperty, rp);
                    ringPulse.BeginAnimation(ScaleTransform.ScaleYProperty, rp);
                }
                c.Children.Add(aura);
                c.Children.Add(new Polygon
                {
                    Points = new PointCollection { new Point(11, 2.5), new Point(19.5, 11), new Point(11, 19.5), new Point(2.5, 11) },
                    Fill = _pal.SpineCopper,
                    Stroke = _pal.SpineCopper,
                    StrokeThickness = 1.3
                });
                Polygon inner = new Polygon
                {
                    Points = new PointCollection { new Point(11, 7.6), new Point(14.4, 11), new Point(11, 14.4), new Point(7.6, 11) },
                    Fill = _pal.SpineSolidFallback
                };
                c.Children.Add(inner);
            }
            else if (kind == "seal-active")
            {
                c.Children.Add(new Polygon
                {
                    Points = new PointCollection { new Point(11, 2.2), new Point(19.8, 11), new Point(11, 19.8), new Point(2.2, 11) },
                    Fill = _pal.SpineMint,
                    Stroke = _pal.SpineMintBright,
                    StrokeThickness = 1.3
                });
                c.Children.Add(new Polyline
                {
                    Points = new PointCollection { new Point(7.8, 11.2), new Point(10.0, 13.4), new Point(14.4, 8.9) },
                    Stroke = _pal.SpineSolidFallback,
                    StrokeThickness = 1.8,
                    StrokeStartLineCap = PenLineCap.Round,
                    StrokeEndLineCap = PenLineCap.Round,
                    StrokeLineJoin = PenLineJoin.Round
                });
            }
            else if (kind == "seal")
            {
                Ellipse halo = new Ellipse
                {
                    Width = 19,
                    Height = 19,
                    Stroke = DossierPalette.Rgba(95, 88, 220, 195),
                    StrokeThickness = 0.9,
                    StrokeDashArray = new DoubleCollection(new double[] { 2, 3 })
                };
                Canvas.SetLeft(halo, 1.5); Canvas.SetTop(halo, 1.5);
                c.Children.Add(halo);
                c.Children.Add(new Polygon
                {
                    Points = new PointCollection { new Point(11, 4.0), new Point(18.0, 11), new Point(11, 18.0), new Point(4.0, 11) },
                    Fill = DossierPalette.Rgba(34, 88, 220, 195),
                    Stroke = _pal.SpineMint,
                    StrokeThickness = 1.2
                });
                Ellipse dot = new Ellipse { Width = 3.4, Height = 3.4, Fill = _pal.SpineMintBright };
                Canvas.SetLeft(dot, 9.3); Canvas.SetTop(dot, 9.3);
                c.Children.Add(dot);
            }
            else if (kind == "done")
            {
                c.Children.Add(new Polygon
                {
                    Points = new PointCollection { new Point(11, 3.2), new Point(18.8, 11), new Point(11, 18.8), new Point(3.2, 11) },
                    Fill = DossierPalette.Rgba(38, 232, 167, 109),
                    Stroke = _pal.SpineCopper,
                    StrokeThickness = 1.2
                });
                Ellipse dot = new Ellipse { Width = 3.6, Height = 3.6, Fill = _pal.SpineCopper };
                Canvas.SetLeft(dot, 9.2); Canvas.SetTop(dot, 9.2);
                c.Children.Add(dot);
            }
            else
            {
                c.Children.Add(new Polygon
                {
                    Points = new PointCollection { new Point(11, 3.5), new Point(18.5, 11), new Point(11, 18.5), new Point(3.5, 11) },
                    Stroke = _pal.SpineDim,
                    StrokeThickness = 1.2
                });
            }
            return c;
        }

        private UIElement BuildBridgeGlyph(Brush leftStroke, Brush rightStroke, double width)
        {
            Canvas c = new Canvas { Width = 44, Height = 12, VerticalAlignment = VerticalAlignment.Center };
            c.Children.Add(new Line { X1 = 1, Y1 = 6, X2 = 16, Y2 = 6, Stroke = leftStroke, StrokeThickness = 1.2, Opacity = 0.65 });
            Line pLeft = new Line { X1 = 1, Y1 = 6, X2 = 16, Y2 = 6, Stroke = leftStroke, StrokeThickness = 1.5, StrokeDashArray = new DoubleCollection { 3, 7 }, StrokeStartLineCap = PenLineCap.Round, StrokeEndLineCap = PenLineCap.Round };
            c.Children.Add(pLeft);

            c.Children.Add(new Polygon
            {
                Points = new PointCollection { new Point(21, 2.2), new Point(24.8, 6), new Point(21, 9.8), new Point(17.2, 6) },
                Fill = _pal.StageSolidFallback,
                Stroke = rightStroke,
                StrokeThickness = 1.2
            });
            Ellipse core = new Ellipse { Width = 2.2, Height = 2.2, Fill = leftStroke };
            Canvas.SetLeft(core, 19.9); Canvas.SetTop(core, 4.9);
            c.Children.Add(core);

            c.Children.Add(new Line { X1 = 26, Y1 = 6, X2 = 39, Y2 = 6, Stroke = rightStroke, StrokeThickness = 1.2, Opacity = 0.7 });
            Line pRight = new Line { X1 = 26, Y1 = 6, X2 = 39, Y2 = 6, Stroke = rightStroke, StrokeThickness = 1.5, StrokeDashArray = new DoubleCollection { 3, 7 }, StrokeStartLineCap = PenLineCap.Round, StrokeEndLineCap = PenLineCap.Round };
            c.Children.Add(pRight);

            if (AllowMotion())
            {
                DoubleAnimation dashAnim = new DoubleAnimation(20.0, 0.0, new Duration(TimeSpan.FromSeconds(2.4))) { RepeatBehavior = RepeatBehavior.Forever };
                pLeft.BeginAnimation(System.Windows.Shapes.Shape.StrokeDashOffsetProperty, dashAnim);
                pRight.BeginAnimation(System.Windows.Shapes.Shape.StrokeDashOffsetProperty, dashAnim);

                Ellipse sigOrb = new Ellipse { Width = 2.5, Height = 2.5, Fill = rightStroke };
                Canvas.SetTop(sigOrb, 4.75);
                c.Children.Add(sigOrb);
                sigOrb.BeginAnimation(Canvas.LeftProperty, new DoubleAnimation(1.5, 37.5, new Duration(TimeSpan.FromSeconds(2.4))) { RepeatBehavior = RepeatBehavior.Forever });
            }

            c.Children.Add(new Polygon
            {
                Points = new PointCollection { new Point(36.2, 3.4), new Point(41.4, 6), new Point(36.2, 8.6) },
                Fill = rightStroke
            });
            if (Math.Abs(width - 44.0) > 0.1) return new Viewbox { Width = width, Height = 11, VerticalAlignment = VerticalAlignment.Center, Child = c };
            return c;
        }

        private UIElement BuildClockIcon(Brush stroke)
        {
            Canvas c = new Canvas { Width = 12, Height = 12, VerticalAlignment = VerticalAlignment.Center, Margin = new Thickness(0, 0, 5, 0) };
            Ellipse ring = new Ellipse { Width = 10.4, Height = 10.4, Stroke = stroke, StrokeThickness = 1.15 };
            Canvas.SetLeft(ring, 0.8); Canvas.SetTop(ring, 0.8);
            c.Children.Add(ring);
            c.Children.Add(new Line { X1 = 6, Y1 = 3.1, X2 = 6, Y2 = 6.1, Stroke = stroke, StrokeThickness = 1.15 });
            c.Children.Add(new Line { X1 = 6, Y1 = 6.1, X2 = 8.3, Y2 = 7.4, Stroke = stroke, StrokeThickness = 1.15 });
            return c;
        }

        private UIElement BuildUndoIcon(string undoKind, Brush stroke)
        {
            Canvas c = new Canvas { Width = 12, Height = 12, VerticalAlignment = VerticalAlignment.Center, Margin = new Thickness(0, 0, 5, 0) };
            if (undoKind == "one-way")
            {
                c.Children.Add(new Line { X1 = 1, Y1 = 6, X2 = 8.5, Y2 = 6, Stroke = stroke, StrokeThickness = 1.3 });
                c.Children.Add(new Line { X1 = 10, Y1 = 2.2, X2 = 10, Y2 = 9.8, Stroke = stroke, StrokeThickness = 1.4 });
                c.Children.Add(new Polygon { Points = new PointCollection { new Point(5.8, 3.3), new Point(8.8, 6), new Point(5.8, 8.7) }, Fill = stroke });
                return c;
            }
            PathFigure pf = new PathFigure { StartPoint = new Point(2.8, 4.5), IsClosed = false, IsFilled = false };
            pf.Segments.Add(new ArcSegment(new Point(9.2, 6.6), new Size(3.8, 3.8), 0, true, SweepDirection.Clockwise, true));
            PathGeometry pg = new PathGeometry();
            pg.Figures.Add(pf);
            c.Children.Add(new System.Windows.Shapes.Path { Data = pg, Stroke = stroke, StrokeThickness = 1.25 });
            c.Children.Add(new Polygon { Points = new PointCollection { new Point(1.4, 2.2), new Point(5.0, 3.0), new Point(2.3, 5.9) }, Fill = stroke });
            return c;
        }

        private UIElement BuildChamferedRiskGauge(int level)
        {
            Canvas c = new Canvas { Width = 36, Height = 6, VerticalAlignment = VerticalAlignment.Center, Margin = new Thickness(0, 1, 0, 0) };
            Brush litCol = level <= 2 ? _pal.Mint : (level == 3 ? _pal.Copper : _pal.Coral);
            for (int i = 0; i < 4; i++)
            {
                double x = i * 9.0;
                bool on = level > 0 && i < level;
                c.Children.Add(new Polygon
                {
                    Points = new PointCollection
                    {
                        new Point(x + 1.4, 0.6),
                        new Point(x + 8.0, 0.6),
                        new Point(x + 6.6, 5.4),
                        new Point(x, 5.4)
                    },
                    Fill = on ? litCol : _pal.PipOff
                });
            }
            return c;
        }

        private UIElement BuildSealMedallion(bool isAmend)
        {
            Canvas c = new Canvas { Width = 54, Height = 54, Margin = new Thickness(0, 0, 16, 0), VerticalAlignment = VerticalAlignment.Center };

            for (int deg = 0; deg < 360; deg += 45)
            {
                double rad = (deg * Math.PI) / 180.0;
                double r1 = (deg % 90 == 0) ? 23.0 : 24.2;
                double r2 = 26.2;
                c.Children.Add(new Line
                {
                    X1 = 27 + Math.Cos(rad) * r1,
                    Y1 = 27 + Math.Sin(rad) * r1,
                    X2 = 27 + Math.Cos(rad) * r2,
                    Y2 = 27 + Math.Sin(rad) * r2,
                    Stroke = (deg % 90 == 0) ? _pal.Copper : _pal.InkMuted,
                    StrokeThickness = (deg % 90 == 0) ? 1.2 : 0.9,
                    Opacity = 0.78
                });
            }

            Ellipse outerOrbit = new Ellipse
            {
                Width = 45,
                Height = 45,
                Stroke = isAmend ? _pal.Copper : _pal.CopperStroke,
                StrokeThickness = 1.1,
                StrokeDashArray = new DoubleCollection(new double[] { 5, 4, 1.5, 4 }),
                Opacity = 0.85
            };
            Canvas.SetLeft(outerOrbit, 4.5); Canvas.SetTop(outerOrbit, 4.5);
            c.Children.Add(outerOrbit);

            Ellipse innerOrbit = new Ellipse
            {
                Width = 35,
                Height = 35,
                Stroke = isAmend ? _pal.Amber : _pal.Mint,
                StrokeThickness = 1.0,
                StrokeDashArray = new DoubleCollection(new double[] { 2, 4 }),
                Opacity = 0.78
            };
            Canvas.SetLeft(innerOrbit, 9.5); Canvas.SetTop(innerOrbit, 9.5);
            c.Children.Add(innerOrbit);

            // Dual Radial Shockwave Rings fired on Seal Ignition
            _shockScale1 = new ScaleTransform(0.65, 0.65);
            _shockwavePrimary = new Ellipse
            {
                Width = 34,
                Height = 34,
                Stroke = _pal.MintBright,
                StrokeThickness = 2.2,
                Opacity = 0.0,
                RenderTransformOrigin = new Point(0.5, 0.5),
                RenderTransform = _shockScale1
            };
            Canvas.SetLeft(_shockwavePrimary, 10); Canvas.SetTop(_shockwavePrimary, 10);
            c.Children.Add(_shockwavePrimary);

            _shockScale2 = new ScaleTransform(0.65, 0.65);
            _shockwaveSecondary = new Ellipse
            {
                Width = 34,
                Height = 34,
                Stroke = _pal.Copper,
                StrokeThickness = 1.5,
                Opacity = 0.0,
                RenderTransformOrigin = new Point(0.5, 0.5),
                RenderTransform = _shockScale2
            };
            Canvas.SetLeft(_shockwaveSecondary, 10); Canvas.SetTop(_shockwaveSecondary, 10);
            c.Children.Add(_shockwaveSecondary);

            c.Children.Add(new Polygon
            {
                Points = new PointCollection { new Point(27, 9), new Point(45, 27), new Point(27, 45), new Point(9, 27) },
                Fill = _pal.WellBg,
                Stroke = _pal.CopperStroke,
                StrokeThickness = 1.35
            });

            Brush mainStroke = isAmend ? _pal.Copper : _pal.Mint;
            Brush mainFill = isAmend ? _pal.CopperSoft : _pal.MintSoft;
            c.Children.Add(new Polygon
            {
                Points = new PointCollection { new Point(27, 14), new Point(40, 27), new Point(27, 40), new Point(14, 27) },
                Stroke = mainStroke,
                StrokeThickness = 1.5,
                Fill = mainFill
            });

            if (isAmend)
            {
                PathFigure fig = new PathFigure { StartPoint = new Point(30.8, 24.2), IsClosed = false, IsFilled = false };
                fig.Segments.Add(new ArcSegment
                {
                    Point = new Point(23.2, 25.2),
                    Size = new Size(4.4, 4.4),
                    SweepDirection = SweepDirection.Clockwise,
                    IsLargeArc = true
                });
                PathGeometry geo = new PathGeometry();
                geo.Figures.Add(fig);
                c.Children.Add(new System.Windows.Shapes.Path
                {
                    Data = geo,
                    Stroke = mainStroke,
                    StrokeThickness = 1.8,
                    StrokeStartLineCap = PenLineCap.Round,
                    StrokeEndLineCap = PenLineCap.Round
                });
                c.Children.Add(new Polyline
                {
                    Points = new PointCollection { new Point(22.6, 22.2), new Point(23.0, 25.6), new Point(26.4, 25.2) },
                    Stroke = mainStroke,
                    StrokeThickness = 1.7,
                    StrokeStartLineCap = PenLineCap.Round,
                    StrokeEndLineCap = PenLineCap.Round,
                    StrokeLineJoin = PenLineJoin.Round
                });
            }
            else
            {
                c.Children.Add(new Polyline
                {
                    Points = new PointCollection { new Point(22.4, 27.3), new Point(25.6, 30.5), new Point(32.0, 23.8) },
                    Stroke = _pal.MintBright,
                    StrokeThickness = 2.1,
                    StrokeStartLineCap = PenLineCap.Round,
                    StrokeEndLineCap = PenLineCap.Round,
                    StrokeLineJoin = PenLineJoin.Round
                });
            }
            return c;
        }

        private UIElement BuildWarnTriangle(Brush stroke)
        {
            Canvas c = new Canvas { Width = 15, Height = 15, Margin = new Thickness(0, 0, 8, 0), VerticalAlignment = VerticalAlignment.Center };
            c.Children.Add(new Polygon
            {
                Points = new PointCollection { new Point(7.5, 2.0), new Point(14.0, 13.2), new Point(1.0, 13.2) },
                Stroke = stroke,
                StrokeThickness = 1.4,
                StrokeLineJoin = PenLineJoin.Round
            });
            c.Children.Add(new Line { X1 = 7.5, Y1 = 6.2, X2 = 7.5, Y2 = 9.4, Stroke = stroke, StrokeThickness = 1.4, StrokeStartLineCap = PenLineCap.Round, StrokeEndLineCap = PenLineCap.Round });
            Ellipse dot = new Ellipse { Width = 1.7, Height = 1.7, Fill = stroke };
            Canvas.SetLeft(dot, 6.65); Canvas.SetTop(dot, 10.9);
            c.Children.Add(dot);
            return c;
        }

        // === Structural & Tactile Control Builders ===
        private Border MakeStrataPill(UIElement icon, string text, string tooltip)
        {
            StackPanel row = new StackPanel { Orientation = Orientation.Horizontal, VerticalAlignment = VerticalAlignment.Center };
            if (icon != null) row.Children.Add(icon);
            row.Children.Add(new TextBlock
            {
                FontFamily = MonoFont,
                FontSize = 12,
                Foreground = _pal.SpineSub,
                TextTrimming = TextTrimming.CharacterEllipsis,
                MaxWidth = 196,
                VerticalAlignment = VerticalAlignment.Center,
                Text = text
            });
            Border b = new Border
            {
                CornerRadius = new CornerRadius(6),
                Background = _pal.SpineWell,
                BorderBrush = _pal.SpineBorder,
                BorderThickness = new Thickness(1),
                Padding = new Thickness(9, 5, 9, 5),
                Margin = new Thickness(0, 0, 0, 5),
                Child = row
            };
            if (!string.IsNullOrEmpty(tooltip)) b.ToolTip = tooltip;
            return b;
        }

        private Border BuildSpineFooterLedger()
        {
            StackPanel sp = new StackPanel();
            List<UiExecChoiceItem> execs = _req.ExecChoices != null ? _req.ExecChoices : new List<UiExecChoiceItem>();
            if (execs.Count > 0)
            {
                StackPanel hdr = new StackPanel { Orientation = Orientation.Horizontal, Margin = new Thickness(0, 0, 0, 4) };
                hdr.Children.Add(BuildUiIcon("diamond-fill", _pal.SpineMint, 11));
                hdr.Children.Add(new TextBlock
                {
                    FontSize = 12,
                    FontWeight = FontWeights.Bold,
                    Foreground = _pal.SpineMint,
                    Margin = new Thickness(6, 0, 0, 0),
                    Text = execs.Count + (execs.Count == 1 ? " auto-resolved choice" : " auto-resolved choices")
                });
                sp.Children.Add(hdr);
                UiExecChoiceItem ec = execs[0];
                sp.Children.Add(new TextBlock
                {
                    FontFamily = MonoFont,
                    FontSize = 11.5,
                    Foreground = _pal.SpineSub,
                    TextTrimming = TextTrimming.CharacterEllipsis,
                    Text = TextSanitizer.SanitizeText(ec.CardId) + " = " + TextSanitizer.SanitizeText(ec.Pick)
                });
            }
            else
            {
                int tCount = _req.TargetsCount > 0 ? _req.TargetsCount : _panels.Count;
                int uCount = _req.UnchangedCount > 0 ? _req.UnchangedCount : _req.HiddenCount;
                StackPanel hdr = new StackPanel { Orientation = Orientation.Horizontal, Margin = new Thickness(0, 0, 0, 3) };
                hdr.Children.Add(BuildUiIcon("diamond-fill", _pal.SpineMint, 11));
                hdr.Children.Add(new TextBlock
                {
                    FontSize = 12,
                    FontWeight = FontWeights.Bold,
                    Foreground = _pal.SpineMint,
                    Margin = new Thickness(6, 0, 0, 0),
                    Text = "Wave scope"
                });
                sp.Children.Add(hdr);
                sp.Children.Add(new TextBlock
                {
                    FontFamily = MonoFont,
                    FontSize = 11.5,
                    Foreground = _pal.SpineSub,
                    Text = tCount + (tCount == 1 ? " target contract" : " target contracts") + (uCount > 0 ? (" · " + uCount + " quiet") : "")
                });
            }

            return new Border
            {
                CornerRadius = new CornerRadius(6),
                Background = _pal.SpineWell,
                BorderBrush = _pal.SpineBorder,
                BorderThickness = new Thickness(1),
                Padding = new Thickness(11, 10, 11, 10),
                Margin = new Thickness(0, 12, 0, 0),
                Child = sp
            };
        }

        private Grid CreateCleanScrollViewer(UIElement content, Thickness pad, bool onSpine, out ScrollViewer svOut)
        {
            ScrollViewer sv = new ScrollViewer
            {
                VerticalScrollBarVisibility = ScrollBarVisibility.Hidden,
                HorizontalScrollBarVisibility = ScrollBarVisibility.Disabled,
                PanningMode = PanningMode.VerticalOnly,
                BorderThickness = new Thickness(0),
                Background = Brushes.Transparent,
                Focusable = false,
                Padding = pad,
                Content = content
            };
            svOut = sv;

            Grid host = new Grid();
            host.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
            host.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });
            Grid.SetColumn(sv, 0);
            host.Children.Add(sv);

            Brush restThumb = onSpine ? _pal.SpineDim : _pal.InkMuted;
            Border rail = new Border
            {
                Width = 10,
                Margin = new Thickness(4, 2, 0, 2),
                CornerRadius = new CornerRadius(4),
                Background = Brushes.Transparent,
                Cursor = Cursors.Hand,
                Visibility = Visibility.Collapsed
            };
            TranslateTransform slide = new TranslateTransform(0, 0);
            Border thumb = new Border
            {
                Width = 4,
                MinHeight = 24,
                CornerRadius = new CornerRadius(2),
                Background = restThumb,
                Opacity = 0.65,
                HorizontalAlignment = HorizontalAlignment.Center,
                VerticalAlignment = VerticalAlignment.Top,
                RenderTransform = slide
            };
            rail.Child = thumb;

            bool dragging = false;
            double startY = 0;
            double startOff = 0;
            double wheelTarget = 0.0;

            DispatcherTimer wheelTimer = new DispatcherTimer { Interval = TimeSpan.FromMilliseconds(14) };
            wheelTimer.Tick += delegate
            {
                double maxS = sv.ScrollableHeight;
                if (maxS <= 0.5)
                {
                    wheelTimer.Stop();
                    return;
                }
                if (wheelTarget < 0.0) wheelTarget = 0.0;
                if (wheelTarget > maxS) wheelTarget = maxS;

                double cur = sv.VerticalOffset;
                double diff = wheelTarget - cur;
                if (Math.Abs(diff) < 0.6)
                {
                    sv.ScrollToVerticalOffset(wheelTarget);
                    wheelTimer.Stop();
                }
                else
                {
                    sv.ScrollToVerticalOffset(cur + diff * 0.34);
                }
            };

            Action<double> glideTo = delegate(double desired)
            {
                double clamped = Math.Max(0.0, Math.Min(sv.ScrollableHeight, desired));
                if (!AllowMotion())
                {
                    wheelTimer.Stop();
                    sv.ScrollToVerticalOffset(clamped);
                    return;
                }
                wheelTarget = clamped;
                if (!wheelTimer.IsEnabled) wheelTimer.Start();
            };

            Action sync = delegate
            {
                double ext = sv.ExtentHeight;
                double vp = sv.ViewportHeight;
                if (ext <= vp + 1.5 || vp <= 0)
                {
                    rail.Visibility = Visibility.Collapsed;
                    return;
                }
                rail.Visibility = Visibility.Visible;
                double trackH = rail.ActualHeight > 12 ? rail.ActualHeight : Math.Max(32.0, vp - 4.0);
                double th = Math.Max(24.0, Math.Min(trackH, Math.Round(trackH * (vp / ext))));
                double maxTop = Math.Max(0.0, trackH - th);
                double ratio = sv.ScrollableHeight > 0 ? Math.Max(0.0, Math.Min(1.0, sv.VerticalOffset / sv.ScrollableHeight)) : 0.0;
                thumb.Height = th;
                slide.Y = Math.Round(maxTop * ratio);
            };

            sv.ScrollChanged += delegate { sync(); };
            rail.SizeChanged += delegate { sync(); };
            rail.MouseEnter += delegate { thumb.Width = 6; thumb.Opacity = 1.0; thumb.Background = _pal.Copper; };
            rail.MouseLeave += delegate { if (!dragging) { thumb.Width = 4; thumb.Opacity = 0.65; thumb.Background = onSpine ? _pal.SpineDim : _pal.InkMuted; } };
            rail.MouseLeftButtonDown += delegate(object s, MouseButtonEventArgs ev)
            {
                ev.Handled = true;
                wheelTimer.Stop();
                double trackH = Math.Max(32.0, rail.ActualHeight);
                double th = thumb.ActualHeight > 0 ? thumb.ActualHeight : 24.0;
                double maxTop = Math.Max(1.0, trackH - th);
                Point pt = ev.GetPosition(rail);
                if (pt.Y >= slide.Y - 4 && pt.Y <= slide.Y + th + 4)
                {
                    dragging = true;
                    startY = pt.Y;
                    startOff = sv.VerticalOffset;
                    rail.CaptureMouse();
                }
                else
                {
                    double r = Math.Max(0.0, Math.Min(1.0, (pt.Y - th * 0.5) / maxTop));
                    glideTo(r * sv.ScrollableHeight);
                }
            };
            rail.MouseMove += delegate(object s, MouseEventArgs ev)
            {
                if (!dragging) return;
                double trackH = Math.Max(32.0, rail.ActualHeight);
                double th = thumb.ActualHeight > 0 ? thumb.ActualHeight : 24.0;
                double maxTop = Math.Max(1.0, trackH - th);
                double dy = ev.GetPosition(rail).Y - startY;
                double next = Math.Max(0.0, Math.Min(sv.ScrollableHeight, startOff + (dy / maxTop) * sv.ScrollableHeight));
                wheelTarget = next;
                sv.ScrollToVerticalOffset(next);
            };
            rail.MouseLeftButtonUp += delegate(object s, MouseButtonEventArgs ev)
            {
                if (dragging)
                {
                    dragging = false;
                    rail.ReleaseMouseCapture();
                    if (!rail.IsMouseOver) { thumb.Width = 4; thumb.Opacity = 0.65; thumb.Background = onSpine ? _pal.SpineDim : _pal.InkMuted; }
                    ev.Handled = true;
                }
            };
            sv.PreviewMouseWheel += delegate(object s, MouseWheelEventArgs ev)
            {
                if (sv.ScrollableHeight > 0)
                {
                    double baseOff = wheelTimer.IsEnabled ? wheelTarget : sv.VerticalOffset;
                    glideTo(baseOff - (ev.Delta * 0.52));
                    ev.Handled = true;
                }
            };

            Grid.SetColumn(rail, 1);
            host.Children.Add(rail);
            return host;
        }

        private static Grid MakeSplitRow(UIElement left, UIElement right, Thickness margin)
        {
            Grid g = new Grid { Margin = margin };
            g.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
            g.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });
            if (left != null) { Grid.SetColumn(left, 0); g.Children.Add(left); }
            if (right != null) { Grid.SetColumn(right, 1); g.Children.Add(right); }
            return g;
        }

        private DossierButton MakeDossierButton(string text, string a11yName, Brush bg, Brush hoverBg, Brush border, Brush fg, Thickness pad, bool liftOnHover, Action onClick)
        {
            TranslateTransform lift = new TranslateTransform(0, 0);
            ScaleTransform press = new ScaleTransform(1.0, 1.0);
            TransformGroup tg = new TransformGroup();
            tg.Children.Add(press);
            tg.Children.Add(lift);

            TextBlock lbl = new TextBlock
            {
                FontFamily = SansFont,
                FontSize = 13,
                FontWeight = FontWeights.Bold,
                Foreground = fg,
                Margin = pad,
                VerticalAlignment = VerticalAlignment.Center,
                HorizontalAlignment = HorizontalAlignment.Center,
                Text = text
            };

            Grid layers = new Grid { ClipToBounds = true };
            layers.Children.Add(new Border
            {
                Height = 1,
                VerticalAlignment = VerticalAlignment.Top,
                Background = _pal.InnerBevel,
                IsHitTestVisible = false
            });
            layers.Children.Add(lbl);

            Border surf = new Border
            {
                CornerRadius = new CornerRadius(6),
                Background = bg,
                BorderBrush = border,
                BorderThickness = new Thickness(1.5),
                MinHeight = 34,
                RenderTransformOrigin = new Point(0.5, 0.5),
                RenderTransform = tg,
                SnapsToDevicePixels = true,
                Child = layers
            };

            ControlTemplate tpl = new ControlTemplate(typeof(Button));
            tpl.VisualTree = new FrameworkElementFactory(typeof(ContentPresenter));

            Button btn = new Button
            {
                Template = tpl,
                Content = surf,
                Background = Brushes.Transparent,
                BorderThickness = new Thickness(0),
                FocusVisualStyle = null,
                Cursor = Cursors.Hand
            };
            AutomationProperties.SetName(btn, a11yName);

            DossierButton db = new DossierButton
            {
                Control = btn,
                Surface = surf,
                Lift = liftOnHover ? lift : null,
                PressScale = press,
                Label = lbl,
                NormalBg = bg,
                HoverBg = hoverBg,
                NormalBorder = border,
                FocusBorder = _pal.Copper,
                NormalFg = fg
            };

            btn.MouseEnter += delegate
            {
                db.SyncVisual(true, AllowMotion());
            };
            btn.MouseLeave += delegate
            {
                if (AllowMotion())
                {
                    press.BeginAnimation(ScaleTransform.ScaleXProperty, new DoubleAnimation(1.0, new Duration(TimeSpan.FromMilliseconds(120))));
                    press.BeginAnimation(ScaleTransform.ScaleYProperty, new DoubleAnimation(1.0, new Duration(TimeSpan.FromMilliseconds(120))));
                }
                else { press.ScaleX = 1.0; press.ScaleY = 1.0; }
                db.SyncVisual(true, AllowMotion());
            };
            btn.PreviewMouseLeftButtonDown += delegate
            {
                if (!db.IsEnabledState) return;
                if (AllowMotion())
                {
                    press.BeginAnimation(ScaleTransform.ScaleXProperty, new DoubleAnimation(0.968, new Duration(TimeSpan.FromMilliseconds(65))));
                    press.BeginAnimation(ScaleTransform.ScaleYProperty, new DoubleAnimation(0.968, new Duration(TimeSpan.FromMilliseconds(65))));
                }
            };
            btn.PreviewMouseLeftButtonUp += delegate
            {
                if (AllowMotion())
                {
                    CubicEase ce = new CubicEase { EasingMode = EasingMode.EaseOut };
                    press.BeginAnimation(ScaleTransform.ScaleXProperty, new DoubleAnimation(1.0, new Duration(TimeSpan.FromMilliseconds(140))) { EasingFunction = ce });
                    press.BeginAnimation(ScaleTransform.ScaleYProperty, new DoubleAnimation(1.0, new Duration(TimeSpan.FromMilliseconds(140))) { EasingFunction = ce });
                }
            };
            btn.GotKeyboardFocus += delegate { db.SyncVisual(false, false); };
            btn.LostKeyboardFocus += delegate { db.SyncVisual(false, false); };
            if (onClick != null) btn.Click += delegate { onClick(); };
            db.SyncVisual(false, false);
            return db;
        }

        private Border MakeBadgePill(string text, Brush bg, Brush border, Brush fg)
        {
            return new Border
            {
                CornerRadius = new CornerRadius(6),
                Background = bg,
                BorderBrush = border,
                BorderThickness = new Thickness(1),
                Padding = new Thickness(9, 2.5, 9, 2.5),
                Margin = new Thickness(6, 0, 0, 0),
                VerticalAlignment = VerticalAlignment.Top,
                Child = new TextBlock
                {
                    FontFamily = SansFont,
                    FontSize = 12,
                    FontWeight = FontWeights.SemiBold,
                    Foreground = fg,
                    Text = text
                }
            };
        }

        private Border MakeInputField(out TextBox box, string initial, bool multiline)
        {
            TextBox tb = new TextBox
            {
                FontFamily = SansFont,
                FontSize = 13.5,
                Foreground = _pal.InkPrimary,
                CaretBrush = _pal.MintBright,
                Background = Brushes.Transparent,
                BorderThickness = new Thickness(0),
                Padding = new Thickness(11, 8, 11, 8),
                AcceptsReturn = multiline,
                TextWrapping = multiline ? TextWrapping.Wrap : TextWrapping.NoWrap,
                MinHeight = multiline ? 68 : 35,
                MaxHeight = multiline ? 116 : 37,
                VerticalScrollBarVisibility = multiline ? ScrollBarVisibility.Auto : ScrollBarVisibility.Hidden,
                Text = initial ?? string.Empty
            };

            Border focusGlow = new Border
            {
                Height = 2,
                CornerRadius = new CornerRadius(0, 0, 8, 8),
                Background = _pal.BorderSubtle,
                VerticalAlignment = VerticalAlignment.Bottom,
                Opacity = 0.65,
                IsHitTestVisible = false
            };

            Grid wellLayers = new Grid();
            wellLayers.Children.Add(tb);
            wellLayers.Children.Add(focusGlow);

            Border wrap = new Border
            {
                CornerRadius = new CornerRadius(8),
                Background = _pal.WellBg,
                BorderBrush = _pal.BorderCard,
                BorderThickness = new Thickness(1),
                Child = wellLayers
            };
            tb.GotKeyboardFocus += delegate
            {
                wrap.BorderBrush = _pal.Mint;
                focusGlow.Background = _pal.HorizonBeamBrush;
                if (AllowMotion()) focusGlow.BeginAnimation(UIElement.OpacityProperty, new DoubleAnimation(1.0, new Duration(TimeSpan.FromMilliseconds(150))));
                else focusGlow.Opacity = 1.0;
            };
            tb.LostKeyboardFocus += delegate
            {
                wrap.BorderBrush = _pal.BorderCard;
                focusGlow.Background = _pal.BorderSubtle;
                if (AllowMotion()) focusGlow.BeginAnimation(UIElement.OpacityProperty, new DoubleAnimation(0.65, new Duration(TimeSpan.FromMilliseconds(150))));
                else focusGlow.Opacity = 0.65;
            };
            box = tb;
            return wrap;
        }

        private Border MakeResizeZone(Cursor cur, int dir, HorizontalAlignment ha, VerticalAlignment va, double w, double h, Thickness margin)
        {
            Border b = new Border
            {
                Background = Brushes.Transparent,
                Cursor = cur,
                HorizontalAlignment = ha,
                VerticalAlignment = va,
                Margin = margin
            };
            if (!double.IsNaN(w)) b.Width = w;
            if (!double.IsNaN(h)) b.Height = h;
            int resizeDir = dir;
            b.MouseLeftButtonDown += delegate(object s, MouseButtonEventArgs ev)
            {
                ev.Handled = true;
                IntPtr hwnd = new WindowInteropHelper(this).Handle;
                if (hwnd != IntPtr.Zero)
                {
                    NativeWin32.ReleaseCapture();
                    NativeWin32.SendMessage(hwnd, 0x0112, (IntPtr)(0xF000 + resizeDir), IntPtr.Zero);
                }
            };
            return b;
        }

        private int TotalSteps()
        {
            return _cards.Count + 1;
        }

        private void RearmGuard()
        {
            _armed = false;
            _armTimer.Stop();
            _armTimer.Start();
            SyncFooterState();
        }

        private bool AllCardsReady()
        {
            for (int i = 0; i < _cards.Count; i++)
            {
                if (_cards[i].CardKind == "question")
                {
                    if (string.IsNullOrEmpty((_answers[i] ?? string.Empty).Trim())) return false;
                }
                else
                {
                    if (string.IsNullOrEmpty((_picks[i] ?? string.Empty).Trim())) return false;
                }
            }
            return true;
        }

        private bool CurrentStepReady()
        {
            if (_stepIndex >= _cards.Count)
            {
                if (!AllCardsReady()) return false;
                bool amend = HasAmendments() || !_req.CanSealDirectly || string.IsNullOrEmpty(_req.ReviewRef);
                if (!amend)
                {
                    string cleanOwner = (_ownerVal ?? string.Empty).Trim();
                    if (string.IsNullOrEmpty(cleanOwner)) return false;
                    if (_req.PolicyApprovers != null && _req.PolicyApprovers.Count > 0 && !_req.PolicyApprovers.Contains(cleanOwner))
                    {
                        return false;
                    }
                }
                return true;
            }
            UiCardItem cur = _cards[_stepIndex];
            if (cur.CardKind == "question") return !string.IsNullOrEmpty((_answers[_stepIndex] ?? string.Empty).Trim());
            return !string.IsNullOrEmpty((_picks[_stepIndex] ?? string.Empty).Trim());
        }

        private bool HasAmendments()
        {
            if (_changeRequestOpen && !string.IsNullOrEmpty((_noteVal ?? string.Empty).Trim())) return true;
            for (int i = 0; i < _cards.Count; i++)
            {
                UiCardItem c = _cards[i];
                if (c.CardKind == "question") return true;
                string prop = TextSanitizer.SanitizeText(c.ProposedPick);
                if (string.IsNullOrEmpty(prop) || _picks[i] != prop) return true;
            }
            return false;
        }

        private int ReviewedCardsCount()
        {
            int n = 0;
            for (int i = 0; i < _cards.Count; i++)
            {
                bool hasVal = _cards[i].CardKind == "question"
                    ? !string.IsNullOrEmpty((_answers[i] ?? string.Empty).Trim())
                    : !string.IsNullOrEmpty((_picks[i] ?? string.Empty).Trim());
                if (hasVal && _reviewedSteps.Contains(i)) n++;
            }
            return n;
        }

        private void RenderReadinessMeter()
        {
            if (_readinessHostBorder == null) return;
            int reviewed = ReviewedCardsCount();
            int total = _cards.Count;
            string statusTxt = total == 0
                ? "SEAL READY"
                : (reviewed == total ? (total + " / " + total + " CONFIRMED") : (reviewed + " / " + total + " REVIEWED"));

            StackPanel box = new StackPanel();
            box.Children.Add(MakeSplitRow(
                new TextBlock { FontFamily = MonoFont, FontSize = 10.5, FontWeight = FontWeights.Bold, Foreground = _pal.SpineSub, Text = "WAVE READINESS" },
                new TextBlock { FontFamily = MonoFont, FontSize = 10.5, FontWeight = FontWeights.ExtraBold, Foreground = _pal.SpineMint, Text = statusTxt },
                new Thickness(0, 0, 0, 7)));

            int slots = Math.Max(1, total + 1);
            Grid cells = new Grid { Height = 8 };
            for (int i = 0; i < slots; i++)
            {
                if (i > 0) cells.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(4) });
                cells.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });

                Brush fill = DossierPalette.Rgb(35, 41, 54);
                Brush border = Brushes.Transparent;
                if (i < total)
                {
                    bool hasVal = _cards[i].CardKind == "question"
                        ? !string.IsNullOrEmpty((_answers[i] ?? string.Empty).Trim())
                        : !string.IsNullOrEmpty((_picks[i] ?? string.Empty).Trim());
                    if (!_specMode && _stepIndex == i) fill = _pal.SpineCopper;
                    else if (hasVal && _reviewedSteps.Contains(i)) fill = _pal.SpineMint;
                    else if (hasVal) { fill = DossierPalette.Rgb(38, 68, 62); border = _pal.SpineMint; }
                }
                else
                {
                    if (!_specMode && _stepIndex >= total) fill = AllCardsReady() ? _pal.SpineMint : _pal.SpineCopper;
                    else if (total == 0 || reviewed == total) fill = _pal.SpineMint;
                }

                Border cBar = new Border
                {
                    CornerRadius = new CornerRadius(2),
                    Background = fill,
                    BorderBrush = border,
                    BorderThickness = new Thickness(border == Brushes.Transparent ? 0 : 1)
                };
                Grid.SetColumn(cBar, i * 2);
                cells.Children.Add(cBar);
            }
            box.Children.Add(cells);

            _readinessHostBorder.Child = box;
        }

        private void SyncSpinePicksInPlace()
        {
            for (int i = 0; i < _cards.Count && i < _spinePickLabels.Count; i++)
            {
                UiCardItem c = _cards[i];
                bool active = !_specMode && _stepIndex == i;
                string chosen = c.CardKind == "question"
                    ? (!string.IsNullOrEmpty((_answers[i] ?? string.Empty).Trim()) ? _answers[i].Trim() : "Open question")
                    : (!string.IsNullOrEmpty(_picks[i]) ? _picks[i] : "Select option");
                string prop = TextSanitizer.SanitizeText(c.ProposedPick);
                bool diverged = c.CardKind != "question" && !string.IsNullOrEmpty(prop) && !string.IsNullOrEmpty(_picks[i]) && _picks[i] != prop;

                TextBlock lbl = _spinePickLabels[i];
                lbl.Text = (diverged ? "updated: " : string.Empty) + chosen;
                lbl.Foreground = diverged ? _pal.SpineCopper : (active ? _pal.SpineCopper : _pal.SpineDim);
            }
            RenderReadinessMeter();
            RedrawRulingChannel();
        }

        private void RedrawRulingChannel()
        {
            if (_rulingCanvas == null) return;
            _rulingCanvas.Children.Clear();
            int n = _spineStepRows.Count;
            if (n == 0) return;

            double cx = 18.0;
            double[] ys = new double[n];
            double[] xs = new double[n];
            for (int i = 0; i < n; i++)
            {
                FrameworkElement r = _spineStepRows[i];
                double yPos = 26.0 + i * 58.0;
                if (r.ActualHeight > 2 && _rulingCanvas.ActualHeight > 20)
                {
                    try
                    {
                        Point pt = r.TranslatePoint(new Point(0, r.ActualHeight * 0.5), _rulingCanvas);
                        yPos = pt.Y;
                    }
                    catch { }
                }
                ys[i] = yPos;
                xs[i] = cx + ((i % 2 == 0) ? -3.5 : 3.5);
            }

            if (n > 1)
            {
                PathFigure fig1 = new PathFigure { StartPoint = new Point(xs[0], ys[0]), IsClosed = false };
                PathFigure fig2 = new PathFigure { StartPoint = new Point(cx - (xs[0] - cx), ys[0]), IsClosed = false };
                for (int i = 0; i < n - 1; i++)
                {
                    double x0 = xs[i], y0 = ys[i];
                    double x1 = xs[i + 1], y1 = ys[i + 1];
                    double my = (y0 + y1) * 0.5;
                    double dir = (i % 2 == 0) ? 1.0 : -1.0;
                    fig1.Segments.Add(new BezierSegment(new Point(x0 + dir * 7.5, my - 6.0), new Point(x1 + dir * 7.5, my + 6.0), new Point(x1, y1), true));
                    double ex0 = cx - (x0 - cx);
                    double ex1 = cx - (x1 - cx);
                    fig2.Segments.Add(new BezierSegment(new Point(ex0 - dir * 5.5, my - 5.0), new Point(ex1 - dir * 5.5, my + 5.0), new Point(ex1, y1), true));
                }
                PathGeometry pg1 = new PathGeometry();
                pg1.Figures.Add(fig1);
                PathGeometry pg2 = new PathGeometry();
                pg2.Figures.Add(fig2);

                _rulingCanvas.Children.Add(new System.Windows.Shapes.Path
                {
                    Data = pg2,
                    Stroke = _pal.SpineMint,
                    StrokeThickness = 1.0,
                    StrokeDashArray = new DoubleCollection { 2.5, 3.5 },
                    Opacity = 0.35
                });
                _rulingCanvas.Children.Add(new System.Windows.Shapes.Path
                {
                    Data = pg1,
                    Stroke = _pal.HorizonBeamBrush,
                    StrokeThickness = 1.5,
                    Opacity = 0.72
                });

                System.Windows.Shapes.Path pulseWave = new System.Windows.Shapes.Path
                {
                    Data = pg1,
                    Stroke = _pal.HorizonBeamBrush,
                    StrokeThickness = 2.0,
                    StrokeDashArray = new DoubleCollection { 6.0, 22.0 },
                    StrokeStartLineCap = PenLineCap.Round,
                    StrokeEndLineCap = PenLineCap.Round,
                    Opacity = 0.95
                };
                _rulingCanvas.Children.Add(pulseWave);

                for (int i = 0; i < n - 1; i++)
                {
                    double my = Math.Round((ys[i] + ys[i + 1]) * 0.5);
                    double tx = (i % 2 == 0) ? 7.0 : 29.0;
                    _rulingCanvas.Children.Add(new Line { X1 = tx - 2.2, Y1 = my, X2 = tx + 2.2, Y2 = my, Stroke = _pal.SpineSub, StrokeThickness = 0.9, Opacity = 0.38 });
                    _rulingCanvas.Children.Add(new Line { X1 = tx, Y1 = my - 2.2, X2 = tx, Y2 = my + 2.2, Stroke = _pal.SpineSub, StrokeThickness = 0.9, Opacity = 0.38 });
                }

                if (AllowMotion())
                {
                    pulseWave.BeginAnimation(System.Windows.Shapes.Shape.StrokeDashOffsetProperty,
                        new DoubleAnimation(56.0, 0.0, new Duration(TimeSpan.FromSeconds(4.2))) { RepeatBehavior = RepeatBehavior.Forever });

                    TranslateTransform orbTr = new TranslateTransform();
                    Ellipse orb = new Ellipse
                    {
                        Width = 4.6,
                        Height = 4.6,
                        Fill = DossierPalette.Rgb(255, 206, 139),
                        Margin = new Thickness(-2.3, -2.3, 0, 0),
                        RenderTransform = orbTr,
                        IsHitTestVisible = false
                    };
                    _rulingCanvas.Children.Add(orb);

                    DoubleAnimationUsingPath animX = new DoubleAnimationUsingPath
                    {
                        PathGeometry = pg1,
                        Source = PathAnimationSource.X,
                        Duration = new Duration(TimeSpan.FromSeconds(4.4)),
                        RepeatBehavior = RepeatBehavior.Forever
                    };
                    DoubleAnimationUsingPath animY = new DoubleAnimationUsingPath
                    {
                        PathGeometry = pg1,
                        Source = PathAnimationSource.Y,
                        Duration = new Duration(TimeSpan.FromSeconds(4.4)),
                        RepeatBehavior = RepeatBehavior.Forever
                    };
                    orbTr.BeginAnimation(TranslateTransform.XProperty, animX);
                    orbTr.BeginAnimation(TranslateTransform.YProperty, animY);
                }
            }

            for (int i = 0; i < n; i++)
            {
                string kind = i < _spineStepKinds.Count ? _spineStepKinds[i] : "idle";
                double nx = xs[i], ny = ys[i];
                bool isAct = (kind == "active" || kind == "seal-active");
                bool isDone = (kind == "done");
                Brush col = (kind == "seal-active") ? _pal.SpineMintBright : (kind == "active" ? _pal.SpineCopper : (isDone ? _pal.SpineMint : _pal.SpineDim));

                if (isAct)
                {
                    Polygon halo = new Polygon
                    {
                        Points = new PointCollection { new Point(nx, ny - 10), new Point(nx + 10, ny), new Point(nx, ny + 10), new Point(nx - 10, ny) },
                        Stroke = col,
                        StrokeThickness = 0.9,
                        Opacity = 0.45
                    };
                    _rulingCanvas.Children.Add(halo);
                }

                double rOuter = isAct ? 6.2 : 5.0;
                Polygon diamond = new Polygon
                {
                    Points = new PointCollection { new Point(nx, ny - rOuter), new Point(nx + rOuter, ny), new Point(nx, ny + rOuter), new Point(nx - rOuter, ny) },
                    Fill = DossierPalette.Rgb(15, 18, 24),
                    Stroke = col,
                    StrokeThickness = isAct ? 1.6 : 1.2
                };
                _rulingCanvas.Children.Add(diamond);

                if (isAct || isDone)
                {
                    double rInner = isAct ? 3.0 : 2.3;
                    Polygon core = new Polygon
                    {
                        Points = new PointCollection { new Point(nx, ny - rInner), new Point(nx + rInner, ny), new Point(nx, ny + rInner), new Point(nx - rInner, ny) },
                        Fill = col
                    };
                    _rulingCanvas.Children.Add(core);
                }
            }
        }

        private void RenderSpine()
        {
            RenderReadinessMeter();
            _spinePickLabels.Clear();
            _spineStepRows = new List<FrameworkElement>();
            _spineStepKinds = new List<string>();
            ControlTemplate bareTpl = new ControlTemplate(typeof(Button));
            bareTpl.VisualTree = new FrameworkElementFactory(typeof(ContentPresenter));

            StackPanel stepStack = new StackPanel();

            for (int i = 0; i < _cards.Count; i++)
            {
                UiCardItem c = _cards[i];
                bool active = !_specMode && _stepIndex == i;
                bool hasVal = c.CardKind == "question"
                    ? !string.IsNullOrEmpty((_answers[i] ?? string.Empty).Trim())
                    : !string.IsNullOrEmpty((_picks[i] ?? string.Empty).Trim());
                bool confirmed = hasVal && _reviewedSteps.Contains(i);
                _spineStepKinds.Add(active ? "active" : (confirmed ? "done" : "idle"));

                StackPanel txt = new StackPanel();
                txt.Children.Add(new TextBlock
                {
                    FontFamily = SansFont,
                    FontSize = 13,
                    FontWeight = FontWeights.Bold,
                    Foreground = active ? _pal.SpineInk : _pal.SpineSub,
                    TextWrapping = TextWrapping.Wrap,
                    MaxHeight = 36,
                    TextTrimming = TextTrimming.CharacterEllipsis,
                    Text = HumanizeSlug(!string.IsNullOrEmpty(c.CardId) ? c.CardId : c.ContractId)
                });

                string chosen = c.CardKind == "question"
                    ? (!string.IsNullOrEmpty((_answers[i] ?? string.Empty).Trim()) ? _answers[i].Trim() : "Open question")
                    : (!string.IsNullOrEmpty(_picks[i]) ? _picks[i] : "Select option");
                string prop = TextSanitizer.SanitizeText(c.ProposedPick);
                bool diverged = c.CardKind != "question" && !string.IsNullOrEmpty(prop) && !string.IsNullOrEmpty(_picks[i]) && _picks[i] != prop;

                TextBlock pickLbl = new TextBlock
                {
                    FontFamily = MonoFont,
                    FontSize = 11.5,
                    Foreground = diverged ? _pal.SpineCopper : (active ? _pal.SpineCopper : _pal.SpineDim),
                    Margin = new Thickness(0, 2, 0, 0),
                    TextTrimming = TextTrimming.CharacterEllipsis,
                    Text = (diverged ? "updated: " : string.Empty) + chosen
                };
                _spinePickLabels.Add(pickLbl);
                txt.Children.Add(pickLbl);

                Border surf = new Border
                {
                    CornerRadius = new CornerRadius(8),
                    Background = active ? _pal.SpineActiveBrush : Brushes.Transparent,
                    BorderThickness = new Thickness(0),
                    Padding = new Thickness(8, 7, 8, 7),
                    Margin = new Thickness(0, 0, 0, 5),
                    Child = txt
                };

                Button stepBtn = new Button
                {
                    Template = bareTpl,
                    Content = surf,
                    Background = Brushes.Transparent,
                    BorderThickness = new Thickness(0),
                    FocusVisualStyle = null,
                    IsEnabled = true,
                    Cursor = Cursors.Hand
                };
                int targetIdx = i;
                bool isAct = active;
                stepBtn.MouseEnter += delegate { if (!isAct) surf.Background = DossierPalette.Rgba(16, 255, 255, 255); };
                stepBtn.MouseLeave += delegate { if (!isAct) surf.Background = Brushes.Transparent; };
                stepBtn.Click += delegate
                {
                    int dir = targetIdx >= _stepIndex ? 1 : -1;
                    _specMode = false;
                    _specHost.Visibility = Visibility.Collapsed;
                    _stageScrollWrap.Visibility = Visibility.Visible;
                    _stepIndex = targetIdx;
                    RearmGuard();
                    RenderAll(true, dir);
                };

                stepStack.Children.Add(stepBtn);
                _spineStepRows.Add(surf);
            }

            bool sealActive = !_specMode && _stepIndex >= _cards.Count;
            bool amend = HasAmendments() || !_req.CanSealDirectly || string.IsNullOrEmpty(_req.ReviewRef);
            bool sealCanJump = AllCardsReady();
            _spineStepKinds.Add(sealActive ? (amend ? "active" : "seal-active") : "seal");

            int tCount = _req.TargetsCount > 0 ? _req.TargetsCount : 1;
            StackPanel stxt = new StackPanel();
            stxt.Children.Add(new TextBlock
            {
                FontFamily = SansFont,
                FontSize = 13,
                FontWeight = FontWeights.Bold,
                Foreground = sealActive ? _pal.SpineInk : _pal.SpineSub,
                Text = amend ? "Review changes" : ("Seal " + tCount + (tCount == 1 ? " contract" : " contracts"))
            });
            string refShort = !string.IsNullOrEmpty(_req.ReviewRef)
                ? (_req.ReviewRef.Length > 19 ? _req.ReviewRef.Substring(0, 19) : _req.ReviewRef)
                : "re-review";
            stxt.Children.Add(new TextBlock
            {
                FontFamily = MonoFont,
                FontSize = 11.5,
                Foreground = sealActive ? (amend ? _pal.SpineCopper : _pal.SpineMint) : _pal.SpineDim,
                Margin = new Thickness(0, 2, 0, 0),
                Text = TextSanitizer.SanitizeText(refShort)
            });

            Border sealSurf = new Border
            {
                CornerRadius = new CornerRadius(8),
                Background = sealActive ? _pal.SpineActiveBrush : Brushes.Transparent,
                BorderThickness = new Thickness(0),
                Padding = new Thickness(8, 7, 8, 7),
                Opacity = sealCanJump ? 1.0 : 0.48,
                Child = stxt
            };
            Button sealBtn = new Button
            {
                Template = bareTpl,
                Content = sealSurf,
                Background = Brushes.Transparent,
                BorderThickness = new Thickness(0),
                FocusVisualStyle = null,
                IsEnabled = sealCanJump,
                Cursor = sealCanJump ? Cursors.Hand : Cursors.Arrow
            };
            bool sAct = sealActive;
            sealBtn.MouseEnter += delegate { if (!sAct && sealCanJump) sealSurf.Background = DossierPalette.Rgba(16, 255, 255, 255); };
            sealBtn.MouseLeave += delegate { if (!sAct) sealSurf.Background = Brushes.Transparent; };
            sealBtn.Click += delegate
            {
                if (!AllCardsReady()) return;
                for (int k = 0; k < _cards.Count; k++) _reviewedSteps.Add(k);
                _specMode = false;
                _specHost.Visibility = Visibility.Collapsed;
                _stageScrollWrap.Visibility = Visibility.Visible;
                _stepIndex = _cards.Count;
                RearmGuard();
                RenderAll(true, 1);
            };
            stepStack.Children.Add(sealBtn);
            _spineStepRows.Add(sealSurf);

            Panel oldParent = _rulingCanvas.Parent as Panel;
            if (oldParent != null) oldParent.Children.Remove(_rulingCanvas);

            Grid spineWaveRow = new Grid();
            spineWaveRow.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(36) });
            spineWaveRow.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
            Grid.SetColumn(_rulingCanvas, 0);
            spineWaveRow.Children.Add(_rulingCanvas);
            Grid.SetColumn(stepStack, 1);
            spineWaveRow.Children.Add(stepStack);
            spineWaveRow.SizeChanged += delegate { RedrawRulingChannel(); };

            ScrollViewer spineScroll;
            _spineHostBorder.Child = CreateCleanScrollViewer(spineWaveRow, new Thickness(0), true, out spineScroll);
            Dispatcher.BeginInvoke(DispatcherPriority.Loaded, new Action(RedrawRulingChannel));
        }

        private Border BuildStratumBar(string filterContractId)
        {
            List<UiRelaxationItem> rels = new List<UiRelaxationItem>();
            for (int i = 0; i < _panels.Count; i++)
            {
                UiContractPanel cp = _panels[i];
                if (cp == null || cp.Relaxations == null) continue;
                if (!string.IsNullOrEmpty(filterContractId) && cp.Id != filterContractId) continue;
                for (int r = 0; r < cp.Relaxations.Count; r++)
                {
                    if (cp.Relaxations[r] != null) rels.Add(cp.Relaxations[r]);
                }
            }
            if (rels.Count == 0) return null;

            UiRelaxationItem first = rels[0];
            StackPanel left = new StackPanel { Orientation = Orientation.Horizontal, VerticalAlignment = VerticalAlignment.Center };
            left.Children.Add(BuildWarnTriangle(_pal.Amber));
            string title = TextSanitizer.SanitizeText(first.Title);
            if (rels.Count > 1) title += " (+" + (rels.Count - 1) + " more)";
            left.Children.Add(new TextBlock
            {
                FontFamily = SansFont,
                FontSize = 12.5,
                FontWeight = FontWeights.SemiBold,
                Foreground = _pal.Amber,
                VerticalAlignment = VerticalAlignment.Center,
                TextWrapping = TextWrapping.Wrap,
                Text = title
            });

            UIElement rightText = null;
            string detail = TextSanitizer.SanitizeText(first.Detail);
            if (!string.IsNullOrEmpty(detail))
            {
                rightText = new TextBlock
                {
                    FontFamily = MonoFont,
                    FontSize = 12,
                    Foreground = _pal.InkBody,
                    Margin = new Thickness(12, 0, 2, 0),
                    VerticalAlignment = VerticalAlignment.Center,
                    Text = detail
                };
            }

            return new Border
            {
                CornerRadius = new CornerRadius(8),
                Background = _pal.AmberWashBrush,
                BorderThickness = new Thickness(0),
                Padding = new Thickness(12, 7, 10, 7),
                Margin = new Thickness(0, 0, 0, 14),
                Child = MakeSplitRow(left, rightText, new Thickness(0))
            };
        }

        // === Focused Spec View with Gliding Copper-to-Mint Tab Indicator ===
        private Border BuildFocusedSpecView(out StackPanel contextHost, out StackPanel tabBodyHost, out ScrollViewer specScrollOut)
        {
            Grid g = new Grid();
            g.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });
            g.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });
            g.RowDefinitions.Add(new RowDefinition { Height = new GridLength(1, GridUnitType.Star) });

            contextHost = new StackPanel();
            Grid.SetRow(contextHost, 0);
            g.Children.Add(contextHost);

            string[] titles = new string[] { "Cases & changes", "Scope & auto", "Snapshot" };
            _tabStripGrid = new Grid { Margin = new Thickness(0, 2, 0, 0) };
            for (int c = 0; c < 3; c++)
            {
                _tabStripGrid.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
            }

            ControlTemplate bareBtn = new ControlTemplate(typeof(Button));
            bareBtn.VisualTree = new FrameworkElementFactory(typeof(ContentPresenter));

            for (int i = 0; i < 3; i++)
            {
                TextBlock lbl = new TextBlock
                {
                    Text = titles[i],
                    FontFamily = SansFont,
                    FontSize = 13.5,
                    FontWeight = FontWeights.SemiBold,
                    Padding = new Thickness(2, 6, 2, 8),
                    HorizontalAlignment = HorizontalAlignment.Left
                };
                Button tb = new Button
                {
                    Template = bareBtn,
                    Content = lbl,
                    Background = Brushes.Transparent,
                    BorderThickness = new Thickness(0),
                    Cursor = Cursors.Hand,
                    FocusVisualStyle = null
                };
                AutomationProperties.SetName(tb, titles[i]);
                int idx = i;
                tb.MouseEnter += delegate { if (_activeTabIndex != idx) _tabLabels[idx].Foreground = _pal.InkPrimary; };
                tb.MouseLeave += delegate { if (_activeTabIndex != idx) _tabLabels[idx].Foreground = _pal.InkBody; };
                tb.Click += delegate { SelectSpecTab(idx, true); };
                _tabButtons[i] = tb;
                _tabLabels[i] = lbl;
                Grid.SetColumn(tb, i);
                _tabStripGrid.Children.Add(tb);
            }

            Grid ulineTrack = new Grid { Height = 2.5, Margin = new Thickness(0, 0, 0, 12) };
            ulineTrack.Children.Add(new Border { Height = 1, Background = _pal.BorderSubtle, VerticalAlignment = VerticalAlignment.Bottom });
            _tabGlideBar = new Border
            {
                Height = 2.4,
                Width = 148,
                CornerRadius = new CornerRadius(1.2),
                Background = _pal.HorizonBeamBrush,
                HorizontalAlignment = HorizontalAlignment.Left,
                RenderTransform = _tabGlideTransform
            };
            ulineTrack.Children.Add(_tabGlideBar);

            StackPanel tabWrap = new StackPanel();
            tabWrap.Children.Add(_tabStripGrid);
            tabWrap.Children.Add(ulineTrack);
            Grid.SetRow(tabWrap, 1);
            g.Children.Add(tabWrap);

            tabBodyHost = new StackPanel { RenderTransform = _specBodySlide };
            Grid specScrollWrap = CreateCleanScrollViewer(tabBodyHost, new Thickness(0, 0, 4, 4), false, out specScrollOut);
            Grid.SetRow(specScrollWrap, 2);
            g.Children.Add(specScrollWrap);

            return new Border { Child = g };
        }

        private void UpdateTabGlideIndicator(bool animate)
        {
            if (_tabStripGrid == null || _tabGlideBar == null) return;
            double totalW = _tabStripGrid.ActualWidth;
            if (totalW <= 20) totalW = Math.Max(420.0, Width - 360.0);
            double colW = Math.Max(90.0, totalW / 3.0);
            _tabGlideBar.Width = Math.Max(80.0, colW - 28.0);
            double targetX = _activeTabIndex * colW;
            if (animate && AllowMotion())
            {
                _tabGlideTransform.BeginAnimation(TranslateTransform.XProperty, new DoubleAnimation(targetX, new Duration(TimeSpan.FromMilliseconds(185)))
                {
                    EasingFunction = new CubicEase { EasingMode = EasingMode.EaseOut }
                });
            }
            else
            {
                _tabGlideTransform.BeginAnimation(TranslateTransform.XProperty, null);
                _tabGlideTransform.X = targetX;
            }
        }

        private void SetSpecMode(bool open)
        {
            _specMode = open;
            SyncModeButtons();
            if (_specMode)
            {
                if (_stepIndex < _cards.Count && !string.IsNullOrEmpty(_cards[_stepIndex].ContractId))
                {
                    _selectedSpecContractId = TextSanitizer.SanitizeText(_cards[_stepIndex].ContractId);
                }
                else if (string.IsNullOrEmpty(_selectedSpecContractId) && _panels.Count > 0)
                {
                    _selectedSpecContractId = TextSanitizer.SanitizeText(_panels[0].Id);
                }
                RefreshSpecContextStrip();
                SelectSpecTab(_activeTabIndex, false);
                _stageScrollWrap.Visibility = Visibility.Collapsed;
                _specHost.Visibility = Visibility.Visible;
                Dispatcher.BeginInvoke(DispatcherPriority.Loaded, new Action(delegate { UpdateTabGlideIndicator(false); }));
                AnimateSlideFade(_specHost, _specSlide, 0.0, 8.0, 190);
            }
            else
            {
                _specHost.Visibility = Visibility.Collapsed;
                _stageScrollWrap.Visibility = Visibility.Visible;
                AnimateSlideFade(_stageHost, _stageSlide, 0.0, -6.0, 170);
            }
            RenderSpine();
            SyncStatusHeader(false);
            SyncFooterState();
        }

        private void ToggleSpecMode()
        {
            SetSpecMode(!_specMode);
        }

        private void RefreshSpecContextStrip()
        {
            _specContextHost.Children.Clear();
            if (_panels.Count <= 1)
            {
                string singleLbl = _stepIndex < _cards.Count
                    ? (TextSanitizer.SanitizeText(_cards[_stepIndex].ContractId) + " · Selected: " + (!string.IsNullOrEmpty(_picks[_stepIndex]) ? _picks[_stepIndex] : "—"))
                    : ("Contract specification · " + (_panels.Count == 1 ? TextSanitizer.SanitizeText(_panels[0].Id) : "wave"));
                _specContextHost.Children.Add(new Border
                {
                    CornerRadius = new CornerRadius(8),
                    Background = _pal.ContextWashBrush,
                    BorderBrush = _pal.BorderSubtle,
                    BorderThickness = new Thickness(1),
                    Padding = new Thickness(12, 7, 12, 7),
                    Margin = new Thickness(0, 0, 0, 8),
                    Child = new TextBlock { FontFamily = MonoFont, FontSize = 12, Foreground = _pal.InkBody, Text = singleLbl }
                });
                return;
            }

            // Click-to-navigate Contract Lens Pill Strip (eliminates long stacked vertical scroll!)
            WrapPanel lensBar = new WrapPanel { Margin = new Thickness(0, 0, 0, 8), VerticalAlignment = VerticalAlignment.Center };
            ControlTemplate barePillTpl = new ControlTemplate(typeof(Button));
            barePillTpl.VisualTree = new FrameworkElementFactory(typeof(ContentPresenter));

            for (int i = 0; i < _panels.Count; i++)
            {
                UiContractPanel cp = _panels[i];
                string cid = TextSanitizer.SanitizeText(cp.Id);
                int nCases = cp.Cases != null ? cp.Cases.Count : 0;
                int nRelax = cp.Relaxations != null ? cp.Relaxations.Count : 0;
                bool active = (_selectedSpecContractId == cid);

                StackPanel pillRow = new StackPanel { Orientation = Orientation.Horizontal, VerticalAlignment = VerticalAlignment.Center };
                pillRow.Children.Add(BuildUiIcon(active ? "diamond-fill" : "diamond-outline", active ? _pal.Mint : _pal.InkMuted, 10));
                pillRow.Children.Add(new TextBlock
                {
                    FontFamily = MonoFont,
                    FontSize = 12,
                    FontWeight = active ? FontWeights.Bold : FontWeights.SemiBold,
                    Foreground = active ? _pal.InkPrimary : _pal.InkBody,
                    Margin = new Thickness(6, 0, 0, 0),
                    Text = cid
                });
                pillRow.Children.Add(new TextBlock
                {
                    FontFamily = MonoFont,
                    FontSize = 11,
                    Foreground = nRelax > 0 ? _pal.Amber : (active ? _pal.Mint : _pal.InkMuted),
                    Margin = new Thickness(7, 0, 0, 0),
                    VerticalAlignment = VerticalAlignment.Center,
                    Text = nCases + (nRelax > 0 ? (" · " + nRelax + " relaxed") : string.Empty)
                });

                Border pillSurf = new Border
                {
                    CornerRadius = new CornerRadius(6),
                    Background = active ? _pal.CardSelectedBrush : _pal.WellBg,
                    BorderBrush = active ? _pal.MintBorder : _pal.BorderSubtle,
                    BorderThickness = new Thickness(1),
                    Padding = new Thickness(11, 6, 11, 6),
                    Margin = new Thickness(0, 0, 7, 4),
                    Child = pillRow
                };
                Button pillBtn = new Button
                {
                    Template = barePillTpl,
                    Content = pillSurf,
                    Background = Brushes.Transparent,
                    BorderThickness = new Thickness(0),
                    Cursor = Cursors.Hand,
                    FocusVisualStyle = null
                };
                string targetCid = cid;
                bool isAct = active;
                pillBtn.MouseEnter += delegate { if (!isAct) pillSurf.BorderBrush = _pal.CopperBorder; };
                pillBtn.MouseLeave += delegate { if (!isAct) pillSurf.BorderBrush = _pal.BorderSubtle; };
                pillBtn.Click += delegate
                {
                    _selectedSpecContractId = targetCid;
                    RefreshSpecContextStrip();
                    SelectSpecTab(_activeTabIndex, true);
                };
                lensBar.Children.Add(pillBtn);
            }

            bool allActive = (_selectedSpecContractId == "*");
            Border allSurf = new Border
            {
                CornerRadius = new CornerRadius(8),
                Background = allActive ? _pal.CardSelectedBrush : Brushes.Transparent,
                BorderBrush = allActive ? _pal.CopperBorder : _pal.BorderSubtle,
                BorderThickness = new Thickness(1),
                Padding = new Thickness(10, 6, 10, 6),
                Margin = new Thickness(0, 0, 0, 4),
                Child = new TextBlock
                {
                    FontFamily = SansFont,
                    FontSize = 12,
                    FontWeight = allActive ? FontWeights.SemiBold : FontWeights.Medium,
                    Foreground = allActive ? _pal.Copper : _pal.InkMuted,
                    Text = "All (" + _panels.Count + ")"
                }
            };
            Button allBtn = new Button
            {
                Template = barePillTpl,
                Content = allSurf,
                Background = Brushes.Transparent,
                BorderThickness = new Thickness(0),
                Cursor = Cursors.Hand,
                FocusVisualStyle = null
            };
            allBtn.MouseEnter += delegate { if (!allActive) allSurf.BorderBrush = _pal.CopperBorder; };
            allBtn.MouseLeave += delegate { if (!allActive) allSurf.BorderBrush = _pal.BorderSubtle; };
            allBtn.Click += delegate
            {
                _selectedSpecContractId = "*";
                RefreshSpecContextStrip();
                SelectSpecTab(_activeTabIndex, true);
            };
            lensBar.Children.Add(allBtn);

            _specContextHost.Children.Add(lensBar);
        }

        private void SelectSpecTab(int idx, bool animate)
        {
            int prev = _activeTabIndex;
            _activeTabIndex = idx;
            for (int i = 0; i < 3; i++)
            {
                if (_tabLabels[i] != null)
                {
                    _tabLabels[i].Foreground = (i == idx) ? _pal.InkPrimary : _pal.InkBody;
                    _tabLabels[i].FontWeight = (i == idx) ? FontWeights.Bold : FontWeights.SemiBold;
                }
            }
            UpdateTabGlideIndicator(animate);
            if (_specTabBody == null) return;
            _specTabBody.Children.Clear();
            if (idx == 0) PopulateCasesTab(_specTabBody);
            else if (idx == 1) PopulateScopeTab(_specTabBody);
            else PopulateSnapshotTab(_specTabBody);
            if (_specScroll != null) _specScroll.ScrollToTop();
            if (animate)
            {
                AnimateSlideFade(_specTabBody, _specBodySlide, idx >= prev ? 9.0 : -9.0, 0.0, 170);
            }
        }

        private void PopulateCasesTab(StackPanel root)
        {
            if (_panels.Count == 0)
            {
                root.Children.Add(new TextBlock { FontFamily = MonoFont, FontSize = 12.5, Foreground = _pal.InkBody, TextWrapping = TextWrapping.Wrap, Text = TextSanitizer.SanitizeText(_req.CasesTab) });
                return;
            }

            if (string.IsNullOrEmpty(_selectedSpecContractId) && _panels.Count > 0)
            {
                _selectedSpecContractId = TextSanitizer.SanitizeText(_panels[0].Id);
            }

            for (int i = 0; i < _panels.Count; i++)
            {
                UiContractPanel cp = _panels[i];
                string cid = TextSanitizer.SanitizeText(cp.Id);
                if (_panels.Count > 1 && _selectedSpecContractId != "*" && cid != _selectedSpecContractId) continue;

                int nCases = cp.Cases != null ? cp.Cases.Count : 0;
                int nRelax = cp.Relaxations != null ? cp.Relaxations.Count : 0;

                // Editorial Contract Masthead & Delta Banner
                StackPanel headerBlock = new StackPanel { Margin = new Thickness(0, 0, 0, 12) };
                StackPanel titleLeft = new StackPanel { Orientation = Orientation.Horizontal, VerticalAlignment = VerticalAlignment.Center };
                titleLeft.Children.Add(new TextBlock
                {
                    FontFamily = SansFont,
                    FontSize = 16.5,
                    FontWeight = FontWeights.Bold,
                    Foreground = _pal.InkPrimary,
                    Margin = new Thickness(0, 0, 8, 0),
                    Text = HumanizeSlug(cid)
                });
                titleLeft.Children.Add(new Border
                {
                    CornerRadius = new CornerRadius(5),
                    Background = _pal.CopperSoft,
                    Padding = new Thickness(7, 2, 7, 2),
                    VerticalAlignment = VerticalAlignment.Center,
                    Child = new TextBlock { FontFamily = MonoFont, FontSize = 11.5, Foreground = _pal.Copper, Text = cid }
                });
                string ck = TextSanitizer.SanitizeText(cp.ChangeKind);
                if (!string.IsNullOrEmpty(ck))
                {
                    titleLeft.Children.Add(MakeBadgePill(ck, _pal.WellBg, _pal.BorderSubtle, _pal.InkBody));
                }
                TextBlock countRight = new TextBlock
                {
                    FontFamily = MonoFont,
                    FontSize = 11.5,
                    Foreground = nRelax > 0 ? _pal.Amber : _pal.Mint,
                    VerticalAlignment = VerticalAlignment.Center,
                    Text = nCases + (nCases == 1 ? " causal rule" : " causal rules") + (nRelax > 0 ? (" · " + nRelax + " relaxed") : " · invariants intact")
                };
                headerBlock.Children.Add(MakeSplitRow(titleLeft, countRight, new Thickness(0)));

                string intent = TextSanitizer.SanitizeText(cp.Intent);
                if (!string.IsNullOrEmpty(intent))
                {
                    headerBlock.Children.Add(new TextBlock
                    {
                        FontSize = 13.8,
                        Foreground = _pal.InkBody,
                        TextWrapping = TextWrapping.Wrap,
                        Margin = new Thickness(0, 5, 0, 0),
                        Text = intent
                    });
                }
                root.Children.Add(headerBlock);

                if (cp.Relaxations != null)
                {
                    for (int r = 0; r < cp.Relaxations.Count; r++)
                    {
                        UiRelaxationItem rw = cp.Relaxations[r];
                        StackPanel rStack = new StackPanel();
                        StackPanel rt = new StackPanel { Orientation = Orientation.Horizontal };
                        rt.Children.Add(BuildWarnTriangle(_pal.Amber));
                        rt.Children.Add(new TextBlock { FontSize = 12.5, FontWeight = FontWeights.SemiBold, Foreground = _pal.Amber, Text = TextSanitizer.SanitizeText(rw.Title) });
                        rStack.Children.Add(rt);
                        string det = TextSanitizer.SanitizeText(rw.Detail);
                        if (!string.IsNullOrEmpty(det))
                        {
                            rStack.Children.Add(new TextBlock { FontFamily = MonoFont, FontSize = 12, Foreground = _pal.InkPrimary, Margin = new Thickness(23, 3, 0, 0), TextWrapping = TextWrapping.Wrap, Text = det });
                        }
                        root.Children.Add(new Border
                        {
                            CornerRadius = new CornerRadius(8),
                            Background = _pal.AmberWashBrush,
                            BorderThickness = new Thickness(0),
                            Padding = new Thickness(12, 8, 12, 8),
                            Margin = new Thickness(0, 0, 0, 12),
                            Child = rStack
                        });
                    }
                }

                // Causal Story Chapters: WHEN (Cause) ──◇──▶ THEN (Effect)
                if (cp.Cases != null && cp.Cases.Count > 0)
                {
                    for (int k = 0; k < cp.Cases.Count; k++)
                    {
                        UiCaseRow cr = cp.Cases[k];
                        bool hasRelaxedClause = false;
                        if (cr.ThenPairs != null)
                        {
                            for (int p = 0; p < cr.ThenPairs.Count; p++)
                            {
                                if (cr.ThenPairs[p].Relaxed) hasRelaxedClause = true;
                            }
                        }

                        StackPanel caseStack = new StackPanel();
                        StackPanel caseLeft = new StackPanel { Orientation = Orientation.Horizontal, VerticalAlignment = VerticalAlignment.Center };
                        string rawCaseId = TextSanitizer.SanitizeText(cr.Id);
                        caseLeft.Children.Add(new Border
                        {
                            CornerRadius = new CornerRadius(4),
                            Background = _pal.CopperSoft,
                            Padding = new Thickness(5.5, 1.5, 5.5, 1.5),
                            Margin = new Thickness(0, 0, 8, 0),
                            VerticalAlignment = VerticalAlignment.Center,
                            Child = new TextBlock { FontFamily = MonoFont, FontSize = 11, FontWeight = FontWeights.Bold, Foreground = _pal.Copper, Text = (k + 1).ToString("00", CultureInfo.InvariantCulture) }
                        });
                        caseLeft.Children.Add(new TextBlock
                        {
                            FontFamily = SansFont,
                            FontSize = 14.5,
                            FontWeight = FontWeights.Bold,
                            Foreground = _pal.InkPrimary,
                            VerticalAlignment = VerticalAlignment.Center,
                            ToolTip = rawCaseId,
                            Text = HumanizeSlug(rawCaseId)
                        });

                        string bdg = TextSanitizer.SanitizeText(cr.Badge);
                        StackPanel rightMeta = new StackPanel { Orientation = Orientation.Horizontal, VerticalAlignment = VerticalAlignment.Center };
                        if (!string.IsNullOrEmpty(bdg))
                        {
                            rightMeta.Children.Add(new Border
                            {
                                CornerRadius = new CornerRadius(5),
                                Background = _pal.WellBg,
                                Padding = new Thickness(7, 2, 7, 2),
                                Child = new TextBlock { FontFamily = MonoFont, FontSize = 11, Foreground = _pal.InkBody, Text = "@" + bdg.ToLowerInvariant() }
                            });
                        }
                        if (hasRelaxedClause)
                        {
                            rightMeta.Children.Add(MakeBadgePill("relaxed", _pal.AmberBg, _pal.AmberBorder, _pal.Amber));
                        }
                        caseStack.Children.Add(MakeSplitRow(caseLeft, rightMeta.Children.Count > 0 ? rightMeta : null, new Thickness(0, 0, 0, 10)));

                        Grid flowGrid = MakeCaseRowGrid();
                        AddCell(flowGrid, 0, BuildClauseWell("WHEN", _pal.Copper, _pal.ContextWashBrush, _pal.CopperBorder, cr.WhenPairs, cr.WhenText, false));
                        AddCell(flowGrid, 1, new Border { Padding = new Thickness(6, 0, 6, 0), VerticalAlignment = VerticalAlignment.Center, Child = BuildBridgeGlyph(_pal.Copper, hasRelaxedClause ? _pal.Amber : _pal.Mint, 52) });
                        AddCell(flowGrid, 2, BuildClauseWell("THEN", hasRelaxedClause ? _pal.Amber : _pal.Mint, hasRelaxedClause ? _pal.AmberWashBrush : _pal.MintWashBrush, hasRelaxedClause ? _pal.AmberBorder : _pal.MintBorder, cr.ThenPairs, cr.ThenText, true));
                        caseStack.Children.Add(flowGrid);

                        root.Children.Add(new Border
                        {
                            CornerRadius = new CornerRadius(12),
                            Background = _pal.CardIdleBrush,
                            BorderBrush = hasRelaxedClause ? _pal.AmberBorder : _pal.BorderSubtle,
                            BorderThickness = new Thickness(1.0),
                            Padding = new Thickness(15, 13, 15, 14),
                            Margin = new Thickness(0, 0, 0, 11),
                            Child = caseStack
                        });
                    }
                }

                if (_selectedSpecContractId == "*" && i < _panels.Count - 1)
                {
                    root.Children.Add(new Border { Height = 1, Background = _pal.BorderSubtle, Margin = new Thickness(0, 10, 0, 16) });
                }
            }
        }

        private static Grid MakeCaseRowGrid()
        {
            Grid g = new Grid();
            g.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1.0, GridUnitType.Star) });
            g.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });
            g.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1.08, GridUnitType.Star) });
            return g;
        }

        private static void AddCell(Grid g, int col, UIElement el)
        {
            Grid.SetColumn(el, col);
            g.Children.Add(el);
        }

        private UIElement BuildClauseWell(string headerTag, Brush tagFg, Brush chamberBg, Brush chamberBorder, List<UiKvPair> pairs, string fallback, bool isThen)
        {
            StackPanel sp = new StackPanel();

            StackPanel kickerLeft = new StackPanel { Orientation = Orientation.Horizontal, VerticalAlignment = VerticalAlignment.Center };
            kickerLeft.Children.Add(BuildUiIcon(isThen ? "diamond-fill" : "diamond-outline", tagFg, 10));
            kickerLeft.Children.Add(new TextBlock
            {
                FontFamily = MonoFont,
                FontSize = 11,
                FontWeight = FontWeights.Bold,
                Foreground = tagFg,
                Margin = new Thickness(5, 0, 0, 0),
                Text = headerTag
            });
            TextBlock roleRight = new TextBlock
            {
                FontFamily = SansFont,
                FontSize = 11.5,
                Foreground = _pal.InkMuted,
                VerticalAlignment = VerticalAlignment.Center,
                Text = isThen ? "Guaranteed effect" : "Trigger condition"
            };
            sp.Children.Add(new Border
            {
                BorderBrush = _pal.BorderSubtle,
                BorderThickness = new Thickness(0, 0, 0, 1),
                Padding = new Thickness(0, 0, 0, 6),
                Margin = new Thickness(0, 0, 0, 8),
                Child = MakeSplitRow(kickerLeft, roleRight, new Thickness(0))
            });

            if (pairs != null && pairs.Count > 0)
            {
                for (int i = 0; i < pairs.Count; i++)
                {
                    UiKvPair kv = pairs[i];
                    string kTxt = TextSanitizer.SanitizeText(kv.Key);
                    string vTxt = TextSanitizer.SanitizeText(kv.Val);

                    if (!isThen)
                    {
                        StackPanel trigRow = new StackPanel { Margin = new Thickness(0, 0, 0, i < pairs.Count - 1 ? 6 : 0) };
                        TextBlock keyHdr = new TextBlock { FontFamily = MonoFont, FontSize = 11.5, Margin = new Thickness(0, 0, 0, 4) };
                        keyHdr.Inlines.Add(new System.Windows.Documents.Run(kTxt) { FontWeight = FontWeights.Bold, Foreground = _pal.Copper });
                        keyHdr.Inlines.Add(new System.Windows.Documents.Run(" =") { Foreground = _pal.InkMuted });
                        trigRow.Children.Add(keyHdr);

                        string[] alts = vTxt.Contains(" | ") ? vTxt.Split(new string[] { " | " }, StringSplitOptions.RemoveEmptyEntries) : new string[] { vTxt };
                        WrapPanel altWrap = new WrapPanel();
                        for (int a = 0; a < alts.Length; a++)
                        {
                            if (a > 0)
                            {
                                altWrap.Children.Add(new TextBlock
                                {
                                    FontStyle = FontStyles.Italic,
                                    FontSize = 11.5,
                                    Foreground = _pal.Copper,
                                    VerticalAlignment = VerticalAlignment.Center,
                                    Margin = new Thickness(0, 0, 5, 4),
                                    Text = "or"
                                });
                            }
                            altWrap.Children.Add(new Border
                            {
                                CornerRadius = new CornerRadius(6),
                                Background = _pal.WellBg,
                                Padding = new Thickness(9, 3.5, 9, 3.5),
                                Margin = new Thickness(0, 0, 5, 4),
                                Child = new TextBlock { FontFamily = MonoFont, FontSize = 12, FontWeight = FontWeights.SemiBold, Foreground = _pal.InkPrimary, TextWrapping = TextWrapping.Wrap, Text = alts[a].Trim() }
                            });
                        }
                        trigRow.Children.Add(altWrap);
                        sp.Children.Add(trigRow);
                    }
                    else
                    {
                        StackPanel lhs = new StackPanel { Orientation = Orientation.Horizontal, VerticalAlignment = VerticalAlignment.Center };
                        lhs.Children.Add(BuildUiIcon(kv.Relaxed ? "diamond-outline" : "check", kv.Relaxed ? _pal.Amber : _pal.Mint, 11));
                        lhs.Children.Add(new TextBlock
                        {
                            FontFamily = MonoFont,
                            FontSize = 12,
                            Foreground = kv.Relaxed ? _pal.Amber : _pal.InkBody,
                            Margin = new Thickness(6, 0, 0, 0),
                            TextWrapping = TextWrapping.Wrap,
                            Text = kTxt
                        });

                        Border rhs = new Border
                        {
                            CornerRadius = new CornerRadius(5),
                            Background = kv.Relaxed ? _pal.AmberBg : _pal.MintSoft,
                            Padding = new Thickness(8, 2, 8, 2),
                            VerticalAlignment = VerticalAlignment.Center,
                            Child = new TextBlock
                            {
                                FontFamily = MonoFont,
                                FontSize = 12,
                                FontWeight = FontWeights.Bold,
                                Foreground = kv.Relaxed ? _pal.Amber : _pal.Mint,
                                Text = vTxt
                            }
                        };

                        sp.Children.Add(new Border
                        {
                            CornerRadius = new CornerRadius(7),
                            Background = kv.Relaxed ? _pal.AmberWashBrush : _pal.WellBg,
                            Padding = new Thickness(10, 5.5, 10, 5.5),
                            Margin = new Thickness(0, 0, 0, i < pairs.Count - 1 ? 6 : 0),
                            Child = MakeSplitRow(lhs, rhs, new Thickness(0))
                        });
                    }
                }
            }
            else
            {
                sp.Children.Add(new TextBlock { FontFamily = MonoFont, FontSize = 12, Foreground = _pal.InkMuted, TextWrapping = TextWrapping.Wrap, Text = !string.IsNullOrEmpty(fallback) ? TextSanitizer.SanitizeText(fallback) : "—" });
            }

            return new Border
            {
                CornerRadius = new CornerRadius(10),
                Background = chamberBg,
                BorderBrush = chamberBorder,
                BorderThickness = new Thickness(1.0),
                Padding = new Thickness(13, 10, 13, 11),
                Child = sp
            };
        }

        private void PopulateScopeTab(StackPanel root)
        {
            for (int i = 0; i < _panels.Count; i++)
            {
                UiContractPanel cp = _panels[i];
                string cid = TextSanitizer.SanitizeText(cp.Id);
                if (_panels.Count > 1 && _selectedSpecContractId != "*" && cid != _selectedSpecContractId) continue;

                StackPanel sp = new StackPanel();
                sp.Children.Add(new TextBlock { FontFamily = MonoFont, FontSize = 13.5, FontWeight = FontWeights.Bold, Foreground = _pal.Copper, Margin = new Thickness(0, 0, 0, 8), Text = cid });
                AppendScopeChipRow(sp, "CODE", cp.Code, _pal.InkPrimary, _pal.WellBg, _pal.BorderSubtle);
                AppendScopeChipRow(sp, "WRITES", cp.Writes, _pal.Copper, _pal.CopperSoft, _pal.CopperBorder);
                AppendScopeChipRow(sp, "READS", cp.Reads, _pal.MintBright, _pal.MintWashBrush, _pal.MintBorder);
                root.Children.Add(new Border
                {
                    CornerRadius = new CornerRadius(10),
                    Background = _pal.CardIdleBrush,
                    BorderBrush = _pal.BorderCard,
                    BorderThickness = new Thickness(1),
                    Padding = new Thickness(15, 12, 15, 10),
                    Margin = new Thickness(0, 0, 0, 10),
                    Child = sp
                });
            }

            if (_req.ExecChoices != null && _req.ExecChoices.Count > 0)
            {
                StackPanel ecSp = new StackPanel();
                ecSp.Children.Add(new TextBlock { FontSize = 13.5, FontWeight = FontWeights.Bold, Foreground = _pal.Mint, Margin = new Thickness(0, 0, 0, 6), Text = "Autonomous execution choices (0 stops)" });
                for (int i = 0; i < _req.ExecChoices.Count; i++)
                {
                    UiExecChoiceItem ec = _req.ExecChoices[i];
                    ecSp.Children.Add(new TextBlock
                    {
                        FontFamily = MonoFont,
                        FontSize = 12.5,
                        Foreground = _pal.MintBright,
                        Margin = new Thickness(0, 3, 0, 0),
                        Text = TextSanitizer.SanitizeText(ec.ContractId) + "#" + TextSanitizer.SanitizeText(ec.CardId) + " = " + TextSanitizer.SanitizeText(ec.Pick)
                    });
                }
                root.Children.Add(new Border
                {
                    CornerRadius = new CornerRadius(6),
                    Background = _pal.MintWashBrush,
                    BorderBrush = _pal.MintBorder,
                    BorderThickness = new Thickness(1),
                    Padding = new Thickness(15, 12, 15, 12),
                    Child = ecSp
                });
            }
        }

        private void AppendScopeChipRow(StackPanel sp, string label, List<string> items, Brush valBrush, Brush chipBg, Brush chipBorder)
        {
            if (items == null || items.Count == 0) return;
            Grid g = new Grid { Margin = new Thickness(0, 0, 0, 6) };
            g.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(68) });
            g.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
            AddCell(g, 0, new TextBlock { FontFamily = MonoFont, FontSize = 11, FontWeight = FontWeights.SemiBold, Foreground = _pal.InkMuted, Margin = new Thickness(0, 4, 0, 0), Text = label });

            WrapPanel chips = new WrapPanel();
            for (int i = 0; i < items.Count; i++)
            {
                chips.Children.Add(new Border
                {
                    CornerRadius = new CornerRadius(5),
                    Background = chipBg,
                    BorderThickness = new Thickness(0),
                    Padding = new Thickness(8, 3, 8, 3),
                    Margin = new Thickness(0, 0, 6, 4),
                    Child = new TextBlock { FontFamily = MonoFont, FontSize = 11.5, Foreground = valBrush, Text = TextSanitizer.SanitizeText(items[i]) }
                });
            }
            AddCell(g, 1, chips);
            sp.Children.Add(g);
        }

        private void PopulateSnapshotTab(StackPanel root)
        {
            StackPanel snapSp = new StackPanel();
            snapSp.Children.Add(new TextBlock { FontSize = 14, FontWeight = FontWeights.Bold, Foreground = _pal.InkPrimary, Margin = new Thickness(0, 0, 0, 6), Text = "Version-bound candidate snapshot" });
            snapSp.Children.Add(new TextBlock { FontFamily = MonoFont, FontSize = 12.5, Foreground = _pal.MintBright, TextWrapping = TextWrapping.Wrap, Text = !string.IsNullOrEmpty(_req.ReviewRef) ? TextSanitizer.SanitizeText(_req.ReviewRef) : "none" });

            List<UiTargetItem> targs = (_req.TargetItems != null && _req.TargetItems.Count > 0) ? _req.TargetItems : _req.TargetsAlt;
            if (targs != null)
            {
                for (int i = 0; i < targs.Count; i++)
                {
                    UiTargetItem t = targs[i];
                    snapSp.Children.Add(new TextBlock
                    {
                        FontFamily = MonoFont,
                        FontSize = 12,
                        Foreground = _pal.InkBody,
                        Margin = new Thickness(0, 6, 0, 0),
                        TextWrapping = TextWrapping.Wrap,
                        Text = TextSanitizer.SanitizeText(t.Path) + "  ·  " + TextSanitizer.SanitizeText(t.BehaviorDigest)
                    });
                }
            }
            root.Children.Add(new Border
            {
                CornerRadius = new CornerRadius(6),
                Background = _pal.MintWashBrush,
                BorderBrush = _pal.MintBorder,
                BorderThickness = new Thickness(1),
                Padding = new Thickness(16, 13, 16, 13),
                Margin = new Thickness(0, 0, 0, 10),
                Child = snapSp
            });

            if (_req.ClaimLimits != null && _req.ClaimLimits.Count > 0)
            {
                StackPanel limSp = new StackPanel();
                limSp.Children.Add(new TextBlock { FontSize = 13.5, FontWeight = FontWeights.Bold, Foreground = _pal.InkPrimary, Margin = new Thickness(0, 0, 0, 6), Text = "Verification boundaries" });
                for (int i = 0; i < _req.ClaimLimits.Count; i++)
                {
                    limSp.Children.Add(new TextBlock { FontSize = 12.5, Foreground = _pal.InkBody, Margin = new Thickness(0, 3, 0, 0), TextWrapping = TextWrapping.Wrap, Text = "• " + TextSanitizer.SanitizeText(_req.ClaimLimits[i]) });
                }
                root.Children.Add(new Border
                {
                    CornerRadius = new CornerRadius(10),
                    Background = _pal.CardIdleBrush,
                    BorderBrush = _pal.BorderCard,
                    BorderThickness = new Thickness(1),
                    Padding = new Thickness(16, 12, 16, 12),
                    Child = limSp
                });
            }
        }

        private void ApplySelectionInPlace(int stepIdx, string optId)
        {
            _reviewedSteps.Add(stepIdx);
            if (_picks[stepIdx] == optId)
            {
                SyncSpinePicksInPlace();
                return;
            }
            _picks[stepIdx] = optId;
            QuarticEase ease = new QuarticEase { EasingMode = EasingMode.EaseOut };

            for (int i = 0; i < _optionHandles.Count; i++)
            {
                OptionRowHandle h = _optionHandles[i];
                bool sel = (h.OptionId == optId);
                if (h.Radio.IsChecked != sel) h.Radio.IsChecked = sel;
                h.CardBorder.Background = sel ? _pal.CardSelectedBrush : _pal.CardIdleBrush;
                h.CardBorder.BorderBrush = sel ? _pal.MintBorder : _pal.BorderCard;
                h.CrownBar.Background = sel ? _pal.HorizonBeamBrush : _pal.InnerSpecularRim;
                if (h.ProseText != null)
                {
                    h.ProseText.Foreground = sel ? _pal.InkPrimary : _pal.InkBody;
                    h.ProseText.FontWeight = sel ? FontWeights.Bold : FontWeights.SemiBold;
                }

                h.Keycap.Background = sel ? _pal.MintSoft : _pal.WellBg;
                h.Keycap.BorderBrush = sel ? _pal.MintBorder : _pal.BorderSubtle;
                h.KeycapText.Foreground = sel ? _pal.MintBright : _pal.InkBody;
                h.OuterGem.Stroke = sel ? _pal.Mint : _pal.InkMuted;

                if (AllowMotion())
                {
                    h.InnerGem.BeginAnimation(UIElement.OpacityProperty, new DoubleAnimation(sel ? 1.0 : 0.0, new Duration(TimeSpan.FromMilliseconds(160))));
                    h.Lift.BeginAnimation(TranslateTransform.YProperty, new DoubleAnimation(sel ? -2.0 : 0.0, new Duration(TimeSpan.FromMilliseconds(180))) { EasingFunction = ease });
                }
                else
                {
                    h.InnerGem.Opacity = sel ? 1.0 : 0.0;
                    h.Lift.Y = sel ? -2.0 : 0.0;
                }
                if (h.DimHost != null)
                {
                    h.DimHost.Opacity = (h.IsDominated && !sel) ? 0.78 : 1.0;
                }
            }
            if (stepIdx >= 0 && stepIdx < _cards.Count)
            {
                string refMode;
                UiOptionItem refOpt = ResolveReferenceOption(_cards[stepIdx], optId, out refMode);
                for (int i = 0; i < _optionHandles.Count; i++)
                {
                    OptionRowHandle h = _optionHandles[i];
                    if (h.DeltaHost != null)
                    {
                        string deltaA11y;
                        PopulateOptionDeltaRow(h.DeltaHost, h.Option, refOpt, refMode, out deltaA11y);
                        AutomationProperties.SetName(h.Radio, h.BaseAutomationName + deltaA11y);
                    }
                }
            }
            SyncSpinePicksInPlace();
            SyncFooterState();
        }

        private static bool IsDominatedOption(UiOptionItem opt)
        {
            if (opt == null || opt.DominatedBy == null) return false;
            for (int i = 0; i < opt.DominatedBy.Count; i++)
            {
                if (!string.IsNullOrEmpty(TextSanitizer.SanitizeText(opt.DominatedBy[i]).Trim())) return true;
            }
            return false;
        }

        private static UiOptionItem ResolveReferenceOption(UiCardItem card, string selectedPick, out string modeLabel)
        {
            modeLabel = string.Empty;
            if (card == null || card.Options == null || card.Options.Count < 2) return null;
            string propId = TextSanitizer.SanitizeText(card.ProposedPick).Trim();
            string selId = TextSanitizer.SanitizeText(selectedPick).Trim();
            if (!string.IsNullOrEmpty(selId))
            {
                for (int i = 0; i < card.Options.Count; i++)
                {
                    UiOptionItem cand = card.Options[i];
                    if (cand != null && TextSanitizer.SanitizeText(cand.Id) == selId && !IsDominatedOption(cand))
                    {
                        modeLabel = (!string.IsNullOrEmpty(propId) && selId == propId) ? "vs Default" : "vs Selected";
                        return cand;
                    }
                }
            }
            if (!string.IsNullOrEmpty(propId))
            {
                for (int i = 0; i < card.Options.Count; i++)
                {
                    UiOptionItem cand = card.Options[i];
                    if (cand != null && TextSanitizer.SanitizeText(cand.Id) == propId && !IsDominatedOption(cand))
                    {
                        modeLabel = "vs Default";
                        return cand;
                    }
                }
            }
            return null;
        }

        private static void ParseOptionAxes(UiOptionItem opt, out double? hours, out int? complexity, out int? risk, out int? undoRank, out string undoLabel, out string parity, out int depCount)
        {
            hours = ParseHours(opt != null ? opt.Effort : null);
            risk = (opt != null && opt.RiskLevel >= 1 && opt.RiskLevel <= 4) ? (int?)opt.RiskLevel : null;
            string uLow = TextSanitizer.SanitizeText(opt != null ? opt.Undo : null).Trim().ToLowerInvariant();
            undoRank = uLow == "easy" ? (int?)1 : (uLow == "costly" ? (int?)2 : (uLow == "one-way" ? (int?)3 : null));
            undoLabel = undoRank.HasValue ? uLow : string.Empty;
            complexity = null;
            parity = string.Empty;
            depCount = 0;
            if (opt != null && opt.Chips != null)
            {
                for (int i = 0; i < opt.Chips.Count; i++)
                {
                    string ch = TextSanitizer.SanitizeText(opt.Chips[i]);
                    if (ch.Length == 14 && ch.StartsWith("complexity ") && ch[11] >= '1' && ch[11] <= '4' && ch.Substring(12) == "/4")
                        complexity = ch[11] - '0';
                    else if (ch == "parity same") parity = "same";
                    else if (ch == "parity diverges") parity = "diverges";
                    else if (ch.StartsWith("dependency ") && ch.Length > 11) depCount++;
                }
            }
        }

        private void PopulateOptionDeltaRow(WrapPanel host, UiOptionItem opt, UiOptionItem refOpt, string modeLabel, out string a11ySummary)
        {
            host.Children.Clear();
            a11ySummary = string.Empty;
            if (opt == null || refOpt == null || IsDominatedOption(refOpt) || TextSanitizer.SanitizeText(opt.Id) == TextSanitizer.SanitizeText(refOpt.Id))
            {
                host.Visibility = Visibility.Collapsed;
                return;
            }
            double? aH, rH;
            int? aC, rC, aR, rR, aU, rU;
            string aUndo, rUndo, aPar, rPar;
            int aDeps, rDeps;
            ParseOptionAxes(opt, out aH, out aC, out aR, out aU, out aUndo, out aPar, out aDeps);
            ParseOptionAxes(refOpt, out rH, out rC, out rR, out rU, out rUndo, out rPar, out rDeps);

            List<string> pros = new List<string>();
            List<string> cons = new List<string>();
            if (aH.HasValue && rH.HasValue && Math.Abs(aH.Value - rH.Value) > 1e-6)
            {
                double dh = Math.Round(aH.Value - rH.Value, 2);
                string hFmt = dh.ToString("0.##", CultureInfo.InvariantCulture);
                if (dh < 0) pros.Add(hFmt + "h effort");
                else cons.Add("+" + hFmt + "h effort");
            }
            if (aC.HasValue && rC.HasValue && aC.Value != rC.Value)
            {
                string txt = "complexity " + aC.Value + "/4 vs " + rC.Value + "/4";
                if (aC.Value < rC.Value) pros.Add(txt); else cons.Add(txt);
            }
            if (aR.HasValue && rR.HasValue && aR.Value != rR.Value)
            {
                string txt = "risk " + aR.Value + "/4 vs " + rR.Value + "/4";
                if (aR.Value < rR.Value) pros.Add(txt); else cons.Add(txt);
            }
            if (aU.HasValue && rU.HasValue && aU.Value != rU.Value)
            {
                string txt = aUndo + " vs " + rUndo + " undo";
                if (aU.Value < rU.Value) pros.Add(txt); else cons.Add(txt);
            }
            if (!string.IsNullOrEmpty(aPar) && !string.IsNullOrEmpty(rPar) && aPar != rPar)
            {
                if (aPar == "same") pros.Add("preserves parity"); else cons.Add("parity diverges");
            }
            if (aDeps != rDeps)
            {
                int dd = aDeps - rDeps;
                if (dd < 0) pros.Add(dd + (dd == -1 ? " dep" : " deps"));
                else cons.Add("+" + dd + (dd == 1 ? " dep" : " deps"));
            }

            if (pros.Count == 0 && cons.Count == 0)
            {
                host.Visibility = Visibility.Collapsed;
                return;
            }
            host.Visibility = Visibility.Visible;
            string effMode = !string.IsNullOrEmpty(modeLabel) ? modeLabel : "vs Selected";
            host.Children.Add(new TextBlock { FontFamily = MonoFont, FontSize = 11, FontWeight = FontWeights.SemiBold, Foreground = _pal.InkMuted, Margin = new Thickness(0, 0, 7, 2), Text = effMode });
            List<string> a11yParts = new List<string>();
            for (int i = 0; i < pros.Count; i++)
            {
                a11yParts.Add(pros[i]);
                host.Children.Add(new TextBlock { FontFamily = MonoFont, FontSize = 11.8, FontWeight = FontWeights.SemiBold, Foreground = _pal.Mint, Margin = new Thickness(0, 0, 7, 2), Text = pros[i] });
            }
            if (pros.Count > 0 && cons.Count > 0)
            {
                host.Children.Add(new TextBlock { FontFamily = MonoFont, FontSize = 11.5, Foreground = _pal.InkMuted, Margin = new Thickness(0, 0, 7, 2), Text = "\u2502" });
            }
            for (int i = 0; i < cons.Count; i++)
            {
                a11yParts.Add(cons[i]);
                host.Children.Add(new TextBlock { FontFamily = MonoFont, FontSize = 11.8, FontWeight = FontWeights.SemiBold, Foreground = _pal.Amber, Margin = new Thickness(0, 0, 7, 2), Text = cons[i] });
            }
            a11ySummary = ", " + effMode + ": " + string.Join(", ", a11yParts.ToArray());
        }

        private static string FormatPanelCommitments(UiContractPanel panel)
        {
            if (panel == null || !panel.HasClauseCounts) return string.Empty;
            List<string> parts = new List<string>();
            int actN = panel.ActiveCasesCount;
            int addN = panel.HasBaseline ? panel.AddedCasesCount : 0;
            if (panel.HasBaseline && addN > 0)
            {
                if (panel.ChangeKind == "added" || addN == actN)
                    parts.Add("+" + addN + (addN == 1 ? " case" : " cases"));
                else
                    parts.Add(actN + (actN == 1 ? " case" : " cases") + " (+" + addN + ")");
            }
            else if (actN > 0)
            {
                parts.Add(actN + (actN == 1 ? " case" : " cases"));
            }
            if (panel.InvariantsCount > 0) parts.Add(panel.InvariantsCount + (panel.InvariantsCount == 1 ? " invariant" : " invariants"));
            if (panel.BudgetsCount > 0) parts.Add(panel.BudgetsCount + (panel.BudgetsCount == 1 ? " budget" : " budgets"));
            if (panel.FormalCount > 0) parts.Add(panel.FormalCount + " formal");
            return string.Join(" \u00B7 ", parts.ToArray());
        }

        private UIElement BuildNestedSelectorCrest(int number, bool selected, out Border keycapOut, out TextBlock keyTxtOut, out Polygon outerGemOut, out Polygon innerGemOut)
        {
            StackPanel sp = new StackPanel { Orientation = Orientation.Horizontal, VerticalAlignment = VerticalAlignment.Center };

            TextBlock kt = new TextBlock
            {
                FontFamily = MonoFont,
                FontSize = 12.5,
                FontWeight = FontWeights.Bold,
                Foreground = selected ? _pal.MintBright : _pal.InkBody,
                HorizontalAlignment = HorizontalAlignment.Center,
                VerticalAlignment = VerticalAlignment.Center,
                Text = number.ToString()
            };
            Border kc = new Border
            {
                Width = 28,
                Height = 28,
                CornerRadius = new CornerRadius(6),
                Background = selected ? _pal.MintSoft : _pal.WellBg,
                BorderBrush = selected ? _pal.MintBorder : _pal.BorderSubtle,
                BorderThickness = new Thickness(1.0),
                Margin = new Thickness(0, 0, 8, 0),
                Child = kt
            };
            sp.Children.Add(kc);

            Canvas gemCv = new Canvas { Width = 14, Height = 14, VerticalAlignment = VerticalAlignment.Center };
            Polygon og = new Polygon
            {
                Points = new PointCollection { new Point(7, 1), new Point(13, 7), new Point(7, 13), new Point(1, 7) },
                Stroke = selected ? _pal.Mint : _pal.InkMuted,
                StrokeThickness = 1.3
            };
            Polygon ig = new Polygon
            {
                Points = new PointCollection { new Point(7, 4.2), new Point(9.8, 7), new Point(7, 9.8), new Point(4.2, 7) },
                Fill = _pal.Mint,
                Opacity = selected ? 1.0 : 0.0
            };
            gemCv.Children.Add(og);
            gemCv.Children.Add(ig);
            sp.Children.Add(gemCv);

            keycapOut = kc;
            keyTxtOut = kt;
            outerGemOut = og;
            innerGemOut = ig;
            return sp;
        }

        private UIElement MakeVerticalStatPillar(string label, UIElement valContent, bool leftDivider)
        {
            StackPanel sp = new StackPanel { VerticalAlignment = VerticalAlignment.Center };
            sp.Children.Add(new TextBlock
            {
                FontFamily = MonoFont,
                FontSize = 10,
                FontWeight = FontWeights.SemiBold,
                Foreground = _pal.InkMuted,
                Margin = new Thickness(0, 0, 0, 3),
                Text = label
            });
            sp.Children.Add(valContent);
            return new Border
            {
                BorderBrush = leftDivider ? _pal.BorderSubtle : Brushes.Transparent,
                BorderThickness = new Thickness(leftDivider ? 1 : 0, 0, 0, 0),
                Padding = new Thickness(leftDivider ? 8 : 0, 0, 4, 0),
                Child = sp
            };
        }

        private void RenderDecisionStep(int idx, UiCardItem card)
        {
            string cid = TextSanitizer.SanitizeText(card.ContractId);
            UiContractPanel panel = (!string.IsNullOrEmpty(cid) && _panelById.ContainsKey(cid)) ? _panelById[cid] : null;

            Border sBar = BuildStratumBar(cid);
            if (sBar != null) _stageHost.Children.Add(sBar);

            // Eyebrow-free Bold 2026 Typographic Header + Post-Heading Metadata
            StackPanel openHeader = new StackPanel { Margin = new Thickness(0, 0, 0, 16) };

            openHeader.Children.Add(new TextBlock
            {
                FontFamily = SansFont,
                FontSize = 22.5,
                FontWeight = FontWeights.ExtraBold,
                Foreground = _pal.InkPrimary,
                LineHeight = 28.5,
                TextWrapping = TextWrapping.Wrap,
                Text = TextSanitizer.SanitizeText(!string.IsNullOrEmpty(card.Ask) ? card.Ask : HumanizeSlug(card.CardId))
            });

            string whyTxt = TextSanitizer.SanitizeText(card.Why).Trim();
            if (string.IsNullOrEmpty(whyTxt) && card.Cases != null && card.Cases.Count > 0)
            {
                List<string> cNames = new List<string>();
                for (int k = 0; k < card.Cases.Count; k++) cNames.Add(TextSanitizer.SanitizeText(card.Cases[k]));
                whyTxt = "Governs cases: " + string.Join(", ", cNames.ToArray()) + ".";
            }
            if (!string.IsNullOrEmpty(whyTxt))
            {
                openHeader.Children.Add(new TextBlock
                {
                    FontFamily = SansFont,
                    FontSize = 13.8,
                    Foreground = _pal.InkBody,
                    LineHeight = 20.5,
                    TextWrapping = TextWrapping.Wrap,
                    Margin = new Thickness(0, 6, 0, 0),
                    Text = whyTxt
                });
            }

            StackPanel metaStrip = new StackPanel { Orientation = Orientation.Horizontal, VerticalAlignment = VerticalAlignment.Center, Margin = new Thickness(0, 8, 0, 0) };
            if (!string.IsNullOrEmpty(cid))
            {
                metaStrip.Children.Add(MakeBadgePill(cid, _pal.WellBg, _pal.BorderSubtle, _pal.Copper));
            }
            string commitSummary = FormatPanelCommitments(panel);
            if (!string.IsNullOrEmpty(commitSummary))
            {
                metaStrip.Children.Add(MakeBadgePill(commitSummary, _pal.MintSoft, _pal.MintBorder, _pal.Mint));
            }
            if (card.ChangedSincePrior)
            {
                metaStrip.Children.Add(MakeBadgePill("Updated", _pal.AmberBg, _pal.AmberBorder, _pal.Amber));
            }
            List<string> rawImps = (card.Impacts != null && card.Impacts.Count > 0) ? card.Impacts : (panel != null ? panel.Impacts : null);
            if (rawImps != null && rawImps.Count > 0)
            {
                List<string> cleanImp = new List<string>();
                for (int k = 0; k < rawImps.Count; k++) cleanImp.Add(TextSanitizer.SanitizeText(rawImps[k]));
                metaStrip.Children.Add(MakeBadgePill("Impacts: " + string.Join(", ", cleanImp.ToArray()), _pal.MintSoft, _pal.MintBorder, _pal.Mint));
            }
            if (metaStrip.Children.Count > 0) openHeader.Children.Add(metaStrip);
            _stageHost.Children.Add(openHeader);

            if (card.CardKind == "question" || card.Options == null || card.Options.Count == 0)
            {
                _stageHost.Children.Add(new TextBlock { FontSize = 13, FontWeight = FontWeights.SemiBold, Foreground = _pal.InkPrimary, Margin = new Thickness(0, 0, 0, 6), Text = "Your answer" });
                TextBox qBox;
                Border qWrap = MakeInputField(out qBox, _answers[idx], false);
                int cIdx = idx;
                qBox.TextChanged += delegate
                {
                    _answers[cIdx] = qBox.Text;
                    if (!string.IsNullOrEmpty((qBox.Text ?? string.Empty).Trim())) _reviewedSteps.Add(cIdx);
                    SyncSpinePicksInPlace();
                    SyncFooterState();
                };
                _stageHost.Children.Add(qWrap);
                return;
            }

            double? minHours = null;
            for (int j = 0; j < card.Options.Count; j++)
            {
                double? h = ParseHours(card.Options[j].Effort);
                if (h.HasValue && (!minHours.HasValue || h.Value < minHours.Value)) minHours = h.Value;
            }

            string propOpt = TextSanitizer.SanitizeText(card.ProposedPick);
            string recOpt = TextSanitizer.SanitizeText(card.RecommendedOption);
            ControlTemplate radioTpl = new ControlTemplate(typeof(RadioButton));
            radioTpl.VisualTree = new FrameworkElementFactory(typeof(ContentPresenter));

            int optCount = card.Options.Count;
            List<KeyValuePair<string, string>>[] optionDetails = new List<KeyValuePair<string, string>>[optCount];
            for (int j = 0; j < optCount; j++)
            {
                optionDetails[j] = new List<KeyValuePair<string, string>>();
                string benefitVal = string.Empty;
                string confVal = string.Empty;
                string compVal = string.Empty;
                string parVal = string.Empty;
                List<string> depVals = new List<string>();
                foreach (string rawChip in card.Options[j].Chips ?? new List<string>())
                {
                    string chip = TextSanitizer.SanitizeText(rawChip);
                    int space = chip.IndexOf(' ');
                    if (space <= 0) continue;
                    string key = chip.Substring(0, space);
                    string value = chip.Substring(space + 1);
                    bool scale = value.Length == 3 && value[0] >= '1' && value[0] <= '4' && value.Substring(1) == "/4";
                    if (key == "leverage" && scale) benefitVal = value;
                    else if (key == "confidence" && scale) confVal = value;
                    else if (key == "complexity" && scale) compVal = value;
                    else if (key == "parity" && (value == "same" || value == "diverges"))
                        parVal = value == "same" ? "Same" : "Diverges";
                    else if (key == "dependency" && value.Length > 0) depVals.Add(value);
                }
                if (!string.IsNullOrEmpty(benefitVal)) optionDetails[j].Add(new KeyValuePair<string, string>("Declared benefit", benefitVal));
                if (!string.IsNullOrEmpty(confVal)) optionDetails[j].Add(new KeyValuePair<string, string>("Confidence", confVal));
                if (!string.IsNullOrEmpty(compVal)) optionDetails[j].Add(new KeyValuePair<string, string>("Complexity", compVal));
                if (!string.IsNullOrEmpty(parVal)) optionDetails[j].Add(new KeyValuePair<string, string>("Parity", parVal));
                for (int d = 0; d < depVals.Count; d++) optionDetails[j].Add(new KeyValuePair<string, string>("Dependency", depVals[d]));
            }
            string refModeInit;
            UiOptionItem refOptInit = ResolveReferenceOption(card, _picks[idx], out refModeInit);
            int cols = optCount == 3 ? 3 : 2;
            int totalCardRows = (optCount + cols - 1) / cols;

            Grid monolithDeck = new Grid { Margin = new Thickness(0, 4, 0, 8) };
            for (int c = 0; c < cols; c++)
            {
                if (c > 0) monolithDeck.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(14) });
                monolithDeck.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
            }
            for (int r = 0; r < totalCardRows; r++)
            {
                if (r > 0) monolithDeck.RowDefinitions.Add(new RowDefinition { Height = new GridLength(14) });
                monolithDeck.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });
            }

            for (int j = 0; j < optCount; j++)
            {
                UiOptionItem opt = card.Options[j];
                bool hasDetails = optionDetails[j].Count > 0;
                string optId = TextSanitizer.SanitizeText(opt.Id);
                string optDoes = TextSanitizer.SanitizeText(opt.Does);
                bool selected = (_picks[idx] == optId);

                Border hKeycap;
                TextBlock hKeyTxt;
                Polygon hOuterGem, hInnerGem;
                UIElement crest = BuildNestedSelectorCrest(j + 1, selected, out hKeycap, out hKeyTxt, out hOuterGem, out hInnerGem);

                StackPanel badges = new StackPanel { Orientation = Orientation.Horizontal, VerticalAlignment = VerticalAlignment.Center };
                bool isProp = !string.IsNullOrEmpty(propOpt) && optId == propOpt;
                bool isRec = (!string.IsNullOrEmpty(recOpt) && optId == recOpt) || opt.IsRecommended;
                bool isDom = IsDominatedOption(opt);
                List<string> domClean = new List<string>();
                if (isDom && opt.DominatedBy != null)
                {
                    for (int d = 0; d < opt.DominatedBy.Count; d++)
                    {
                        string dm = TextSanitizer.SanitizeText(opt.DominatedBy[d]).Trim();
                        if (!string.IsNullOrEmpty(dm)) domClean.Add(dm);
                    }
                }
                bool diverges = false;
                if (opt.Chips != null)
                {
                    for (int ch = 0; ch < opt.Chips.Count; ch++)
                    {
                        string chip = opt.Chips[ch];
                        if (chip == "\u2260 diverges" || chip == "diverges" || chip == "parity diverges") diverges = true;
                    }
                }
                if (isProp && isRec)
                {
                    badges.Children.Add(MakeBadgePill("Optimal", _pal.MintSoft, _pal.MintBorder, _pal.Mint));
                }
                else
                {
                    if (isRec) badges.Children.Add(MakeBadgePill("Recommended", _pal.MintSoft, _pal.MintBorder, _pal.Mint));
                    if (isProp) badges.Children.Add(MakeBadgePill("Default", _pal.CopperSoft, _pal.CopperBorder, _pal.Copper));
                }
                if (domClean.Count > 0)
                {
                    badges.Children.Add(MakeBadgePill("Dominated by " + string.Join(", ", domClean.ToArray()), _pal.AmberBg, _pal.AmberBorder, _pal.Amber));
                }
                if (diverges) badges.Children.Add(MakeBadgePill("Diverges", _pal.AmberBg, _pal.AmberBorder, _pal.Amber));

                Grid topCrestRow = MakeSplitRow(crest, badges.Children.Count > 0 ? badges : null, new Thickness(0, 0, 0, 12));

                StackPanel midBody = new StackPanel { Margin = new Thickness(0, 0, 0, 16) };
                if (!string.IsNullOrEmpty(optDoes))
                {
                    midBody.Children.Add(new TextBlock
                    {
                        FontFamily = MonoFont,
                        FontSize = 11.5,
                        FontWeight = FontWeights.SemiBold,
                        Foreground = selected ? _pal.Mint : _pal.Copper,
                        Margin = new Thickness(0, 0, 0, 6),
                        TextTrimming = TextTrimming.CharacterEllipsis,
                        Text = optId
                    });
                }

                TextBlock proseTxt = new TextBlock
                {
                    FontFamily = SansFont,
                    FontSize = cols == 3 ? 13.8 : 14.5,
                    FontWeight = selected ? FontWeights.SemiBold : FontWeights.Medium,
                    Foreground = selected ? _pal.InkPrimary : _pal.InkBody,
                    LineHeight = cols == 3 ? 19.5 : 21.0,
                    TextWrapping = TextWrapping.Wrap,
                    Text = !string.IsNullOrEmpty(optDoes) ? optDoes : optId
                };
                midBody.Children.Add(proseTxt);
                WrapPanel deltaRow = new WrapPanel { Margin = new Thickness(0, 8, 0, 0) };
                string deltaA11yInit;
                PopulateOptionDeltaRow(deltaRow, opt, refOptInit, refModeInit, out deltaA11yInit);
                midBody.Children.Add(deltaRow);

                // Recessed 3-Pillar Stat Pedestal at bottom of vertical monolith
                Grid statGrid = new Grid();
                statGrid.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(0.98, GridUnitType.Star) });
                statGrid.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(0.64, GridUnitType.Star) });
                statGrid.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1.28, GridUnitType.Star) });

                string effStr = TextSanitizer.SanitizeText(opt.Effort);
                double? hVal = ParseHours(effStr);
                string deltaStr = (hVal.HasValue && minHours.HasValue && hVal.Value > minHours.Value)
                    ? (" +" + (hVal.Value - minHours.Value).ToString("0.#", CultureInfo.InvariantCulture) + "h")
                    : string.Empty;
                StackPanel effRow = new StackPanel { Orientation = Orientation.Horizontal, VerticalAlignment = VerticalAlignment.Center };
                effRow.Children.Add(BuildClockIcon(_pal.CopperStroke));
                TextBlock effTb = new TextBlock { FontFamily = MonoFont, FontSize = 12.5, Margin = new Thickness(4, 0, 0, 0), VerticalAlignment = VerticalAlignment.Center, TextTrimming = TextTrimming.CharacterEllipsis };
                effTb.Inlines.Add(new System.Windows.Documents.Run(!string.IsNullOrEmpty(effStr) ? effStr : "—") { FontWeight = FontWeights.Bold, Foreground = _pal.InkPrimary });
                if (!string.IsNullOrEmpty(deltaStr))
                {
                    effTb.Inlines.Add(new System.Windows.Documents.Run(deltaStr) { FontSize = 10.8, FontWeight = FontWeights.SemiBold, Foreground = _pal.InkMuted });
                }
                effRow.Children.Add(effTb);
                AddCell(statGrid, 0, MakeVerticalStatPillar("EFFORT", effRow, false));

                StackPanel riskStack = new StackPanel { VerticalAlignment = VerticalAlignment.Center };
                riskStack.Children.Add(new TextBlock { FontFamily = MonoFont, FontSize = 12.5, FontWeight = FontWeights.Bold, Foreground = _pal.InkPrimary, Margin = new Thickness(0, 0, 0, 3), Text = opt.RiskLevel > 0 ? (opt.RiskLevel + "/4") : "—" });
                riskStack.Children.Add(BuildChamferedRiskGauge(opt.RiskLevel));
                AddCell(statGrid, 1, MakeVerticalStatPillar("RISK", riskStack, true));

                string undoRaw = TextSanitizer.SanitizeText(opt.Undo).Trim();
                string undoLower = undoRaw.ToLowerInvariant();
                string undoClean = !string.IsNullOrEmpty(undoRaw) ? (char.ToUpperInvariant(undoRaw[0]) + undoRaw.Substring(1)) : "—";
                Brush undoBrush = undoLower == "one-way" ? _pal.Amber : (undoLower == "costly" ? _pal.Copper : _pal.Mint);
                StackPanel undoRow = new StackPanel { Orientation = Orientation.Horizontal, VerticalAlignment = VerticalAlignment.Center };
                undoRow.Children.Add(BuildUndoIcon(undoLower, undoBrush));
                undoRow.Children.Add(new TextBlock { FontSize = 12.5, FontWeight = FontWeights.Bold, Foreground = undoBrush, Margin = new Thickness(4, 0, 0, 0), VerticalAlignment = VerticalAlignment.Center, TextTrimming = TextTrimming.CharacterEllipsis, Text = undoClean });
                AddCell(statGrid, 2, MakeVerticalStatPillar("UNDO", undoRow, true));

                Border pedestal = new Border
                {
                    CornerRadius = new CornerRadius(0, 0, hasDetails ? 0 : 10, hasDetails ? 0 : 10),
                    Background = _pal.WellBg,
                    BorderBrush = _pal.BorderSubtle,
                    BorderThickness = new Thickness(0, 1, 0, 0),
                    Padding = new Thickness(10, 8, 9, 9),
                    Child = statGrid
                };

                Grid cardAnatomy = new Grid();
                cardAnatomy.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });
                cardAnatomy.RowDefinitions.Add(new RowDefinition { Height = new GridLength(1, GridUnitType.Star) });
                cardAnatomy.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });

                Border topPad = new Border { Padding = new Thickness(15, 14, 15, 0), Child = topCrestRow };
                Border midPad = new Border { Padding = new Thickness(15, 0, 15, 4), Child = midBody };
                Grid.SetRow(topPad, 0);
                Grid.SetRow(midPad, 1);
                Grid.SetRow(pedestal, 2);
                cardAnatomy.Children.Add(topPad);
                cardAnatomy.Children.Add(midPad);
                cardAnatomy.Children.Add(pedestal);

                // Stepped Tactile Neo-Brutalist Plinth
                Grid cardLayers = new Grid { ClipToBounds = true };

                RadialGradientBrush spotBrush = new RadialGradientBrush
                {
                    Center = new Point(0.5, 0.25),
                    GradientOrigin = new Point(0.5, 0.25),
                    RadiusX = 0.72,
                    RadiusY = 0.62
                };
                Color spotCol = _pal.IsLight ? Color.FromArgb(24, 184, 80, 20) : Color.FromArgb(28, 240, 163, 101);
                spotBrush.GradientStops.Add(new GradientStop(spotCol, 0.0));
                spotBrush.GradientStops.Add(new GradientStop(Color.FromArgb(0, spotCol.R, spotCol.G, spotCol.B), 1.0));

                Border spotlightLayer = new Border
                {
                    CornerRadius = new CornerRadius(5),
                    Background = spotBrush,
                    Opacity = 0.0,
                    IsHitTestVisible = false
                };
                cardLayers.Children.Add(spotlightLayer);

                Border topCrownRim = new Border
                {
                    Height = 2.0,
                    VerticalAlignment = VerticalAlignment.Top,
                    Background = selected ? _pal.HorizonBeamBrush : _pal.InnerSpecularRim,
                    IsHitTestVisible = false
                };
                cardLayers.Children.Add(topCrownRim);
                cardLayers.Children.Add(cardAnatomy);

                Border cardBorder = new Border
                {
                    CornerRadius = hasDetails ? new CornerRadius(11, 11, 0, 0) : new CornerRadius(11),
                    Background = selected ? _pal.CardSelectedBrush : _pal.CardIdleBrush,
                    BorderBrush = selected ? _pal.MintBorder : _pal.BorderCard,
                    BorderThickness = new Thickness(1.0),
                    MinHeight = 192,
                    SnapsToDevicePixels = true,
                    Child = cardLayers
                };

                TranslateTransform rowLift = new TranslateTransform(0, selected ? -2.0 : 0.0);
                Grid monolith3D = new Grid { Opacity = (isDom && !selected) ? 0.78 : 1.0 };
                monolith3D.Children.Add(cardBorder);

                RadioButton rb = new RadioButton
                {
                    GroupName = "Step_" + idx,
                    IsChecked = selected,
                    Template = radioTpl,
                    Content = monolith3D,
                    FocusVisualStyle = null,
                    Cursor = Cursors.Hand,
                    HorizontalContentAlignment = HorizontalAlignment.Stretch,
                    VerticalContentAlignment = VerticalAlignment.Stretch
                };
                string domSuffix = domClean.Count > 0 ? (", Dominated by " + string.Join(", ", domClean.ToArray())) : string.Empty;
                string baseA11y = (!string.IsNullOrEmpty(optDoes) ? optDoes : optId) + domSuffix + ", Effort " + effStr + ", Risk " + opt.RiskLevel + " of 4, Undo " + undoClean;
                AutomationProperties.SetName(rb, baseA11y + deltaA11yInit);

                OptionRowHandle handle = new OptionRowHandle
                {
                    OptionId = optId,
                    Index = j,
                    Option = opt,
                    IsDominated = isDom,
                    DimHost = monolith3D,
                    DeltaHost = deltaRow,
                    BaseAutomationName = baseA11y,
                    Radio = rb,
                    CardBorder = cardBorder,
                    SpotlightBrush = spotBrush,
                    SpotlightLayer = spotlightLayer,
                    CrownBar = topCrownRim,
                    Lift = rowLift,
                    Keycap = hKeycap,
                    KeycapText = hKeyTxt,
                    ProseText = proseTxt,
                    OuterGem = hOuterGem,
                    InnerGem = hInnerGem
                };
                _optionHandles.Add(handle);

                int capStep = idx;
                string capId = optId;
                rb.Checked += delegate { ApplySelectionInPlace(capStep, capId); };
                rb.PreviewMouseLeftButtonUp += delegate
                {
                    if (_picks[capStep] == capId && !_reviewedSteps.Contains(capStep))
                    {
                        _reviewedSteps.Add(capStep);
                        SyncSpinePicksInPlace();
                    }
                };
                rb.MouseMove += delegate(object s, MouseEventArgs mev)
                {
                    if (cardBorder.ActualWidth > 10 && cardBorder.ActualHeight > 10)
                    {
                        Point p = mev.GetPosition(cardBorder);
                        Point norm = new Point(Math.Max(0.0, Math.Min(1.0, p.X / cardBorder.ActualWidth)), Math.Max(0.0, Math.Min(1.0, p.Y / cardBorder.ActualHeight)));
                        spotBrush.Center = norm;
                        spotBrush.GradientOrigin = norm;
                        spotlightLayer.Opacity = 1.0;
                    }
                };
                rb.MouseEnter += delegate
                {
                    spotlightLayer.Opacity = 1.0;
                    bool isSel = (_picks[capStep] == capId);
                    if (!isSel)
                    {
                        cardBorder.Background = _pal.CardHoverBrush;
                        cardBorder.BorderBrush = _pal.CopperBorder;
                        topCrownRim.Background = _pal.Copper;
                        if (AllowMotion())
                        {
                            rowLift.BeginAnimation(TranslateTransform.YProperty, new DoubleAnimation(-2.0, new Duration(TimeSpan.FromMilliseconds(140)))
                            {
                                EasingFunction = new CubicEase { EasingMode = EasingMode.EaseOut }
                            });
                        }
                    }
                };
                rb.MouseLeave += delegate
                {
                    spotlightLayer.Opacity = 0.0;
                    bool isSel = (_picks[capStep] == capId);
                    if (!isSel)
                    {
                        cardBorder.Background = _pal.CardIdleBrush;
                        cardBorder.BorderBrush = _pal.BorderCard;
                        topCrownRim.Background = _pal.InnerSpecularRim;
                        if (AllowMotion())
                        {
                            rowLift.BeginAnimation(TranslateTransform.YProperty, new DoubleAnimation(0.0, new Duration(TimeSpan.FromMilliseconds(150)))
                            {
                                EasingFunction = new CubicEase { EasingMode = EasingMode.EaseOut }
                            });
                        }
                    }
                    else if (AllowMotion())
                    {
                        rowLift.BeginAnimation(TranslateTransform.YProperty, new DoubleAnimation(-2.0, new Duration(TimeSpan.FromMilliseconds(140)))
                        {
                            EasingFunction = new CubicEase { EasingMode = EasingMode.EaseOut }
                        });
                    }
                };
                rb.PreviewMouseLeftButtonDown += delegate
                {
                    if (AllowMotion())
                    {
                        rowLift.BeginAnimation(TranslateTransform.YProperty, new DoubleAnimation(1.0, new Duration(TimeSpan.FromMilliseconds(70))));
                    }
                };
                rb.GotKeyboardFocus += delegate
                {
                    if (InputManager.Current != null && InputManager.Current.MostRecentInputDevice is KeyboardDevice)
                        cardBorder.BorderBrush = _pal.Copper;
                };
                rb.LostKeyboardFocus += delegate { cardBorder.BorderBrush = (_picks[capStep] == capId) ? _pal.MintBorder : _pal.BorderCard; };

                AnimateCascadeItem(rb, j);
                Grid optionEntry = new Grid { Margin = new Thickness(0, 2, 0, 4), RenderTransform = rowLift };
                optionEntry.RowDefinitions.Add(new RowDefinition { Height = new GridLength(1, GridUnitType.Star) });
                optionEntry.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });
                optionEntry.Children.Add(rb);
                if (hasDetails)
                {
                    StackPanel detailRows = new StackPanel { Margin = new Thickness(12, 0, 12, 8) };
                    foreach (KeyValuePair<string, string> detail in optionDetails[j])
                    {
                        Grid row = new Grid();
                        row.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(0.9, GridUnitType.Star) });
                        row.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1.1, GridUnitType.Star) });
                        row.Children.Add(new TextBlock { Text = detail.Key, Foreground = _pal.InkMuted, FontSize = 12.5, TextWrapping = TextWrapping.Wrap });
                        FrameworkElement value = detail.Key == "Declared benefit"
                            ? (FrameworkElement)BuildOptionScore(detail.Value[0] - '0', _pal.Copper)
                            : (detail.Key == "Complexity"
                                ? (FrameworkElement)BuildOptionScore(detail.Value[0] - '0', _pal.InkBody)
                                : new TextBlock { Text = detail.Value, Foreground = detail.Key == "Parity" && detail.Value == "Diverges" ? _pal.Amber : _pal.InkPrimary, FontSize = 12.5, FontWeight = FontWeights.SemiBold, TextWrapping = TextWrapping.Wrap });
                        AddCell(row, 1, value);
                        detailRows.Children.Add(new Border { BorderBrush = _pal.BorderSubtle, BorderThickness = new Thickness(0, 1, 0, 0), Padding = new Thickness(0, 5, 0, 5), Child = row });
                    }
                    Expander details = new Expander
                    {
                        Header = "Option details",
                        Foreground = _pal.InkBody,
                        MinHeight = 34,
                        Content = detailRows
                    };
                    AutomationProperties.SetName(details, "Option details: " + optId);
                    Border detailsWell = new Border
                    {
                        Background = _pal.WellBg,
                        BorderThickness = new Thickness(1, 0, 1, 1),
                        CornerRadius = new CornerRadius(0, 0, 11, 11),
                        Padding = new Thickness(3),
                        Child = details
                    };
                    detailsWell.SetBinding(Border.BorderBrushProperty, new System.Windows.Data.Binding("BorderBrush") { Source = cardBorder });
                    Grid.SetRow(detailsWell, 1);
                    optionEntry.Children.Add(detailsWell);
                }
                Grid.SetColumn(optionEntry, (j % cols) * 2);
                Grid.SetRow(optionEntry, (j / cols) * 2);
                monolithDeck.Children.Add(optionEntry);
            }

            _stageHost.Children.Add(monolithDeck);
        }

        private StackPanel BuildOptionScore(int score, Brush fill)
        {
            StackPanel readout = new StackPanel { Orientation = Orientation.Horizontal, VerticalAlignment = VerticalAlignment.Center };
            for (int i = 0; i < 4; i++)
            {
                Brush accent = SystemParameters.HighContrast ? SystemColors.WindowTextBrush : fill;
                readout.Children.Add(new Border
                {
                    Width = 8, Height = 6, CornerRadius = new CornerRadius(2), BorderThickness = new Thickness(1),
                    Margin = new Thickness(0, 0, 3, 0), VerticalAlignment = VerticalAlignment.Center,
                    BorderBrush = i < score || SystemParameters.HighContrast ? accent : _pal.InkMuted,
                    Background = i < score ? accent : Brushes.Transparent
                });
            }
            readout.Children.Add(new TextBlock { Text = score + "/4", FontFamily = MonoFont, FontSize = 12.5, FontWeight = FontWeights.SemiBold, Foreground = _pal.InkPrimary, Margin = new Thickness(2, 0, 0, 0) });
            return readout;
        }

        private UIElement MakeLedgerMetric(string label, string val)
        {
            TextBlock tb = new TextBlock { FontFamily = MonoFont, FontSize = 13.5, VerticalAlignment = VerticalAlignment.Center };
            tb.Inlines.Add(new System.Windows.Documents.Run(label) { Foreground = _pal.InkMuted });
            tb.Inlines.Add(new System.Windows.Documents.Run(val) { FontWeight = FontWeights.Bold, Foreground = _pal.InkPrimary });
            return tb;
        }

        private UIElement BuildSealPanelRow(UiContractPanel p)
        {
            StackPanel sp = new StackPanel();
            string pid = TextSanitizer.SanitizeText(!string.IsNullOrEmpty(p.Id) ? p.Id : p.File);
            string cSum = FormatPanelCommitments(p);
            UIElement rightChip = null;
            if (!string.IsNullOrEmpty(cSum))
            {
                string targetCid = pid;
                DossierButton cBtn = MakeDossierButton(cSum, "Open contract cases for " + pid, _pal.MintSoft, _pal.BtnHover, _pal.MintBorder, _pal.Mint, new Thickness(9, 2, 9, 2), false, delegate
                {
                    if (!string.IsNullOrEmpty(targetCid)) _selectedSpecContractId = targetCid;
                    _activeTabIndex = 0;
                    SetSpecMode(true);
                });
                cBtn.Control.MinHeight = 24;
                cBtn.Surface.MinHeight = 24;
                rightChip = cBtn.Control;
            }
            sp.Children.Add(MakeSplitRow(
                new TextBlock { FontFamily = MonoFont, FontSize = 12.5, FontWeight = FontWeights.Bold, Foreground = _pal.Copper, VerticalAlignment = VerticalAlignment.Center, Text = pid },
                rightChip,
                new Thickness(0)));
            string intentTxt = TextSanitizer.SanitizeText(p.Intent).Trim();
            if (!string.IsNullOrEmpty(intentTxt))
            {
                sp.Children.Add(new TextBlock { FontSize = 13, Foreground = _pal.InkBody, Margin = new Thickness(0, 3, 0, 0), TextWrapping = TextWrapping.Wrap, Text = intentTxt });
            }
            return sp;
        }

        private void RenderSummaryStep()
        {
            Border sBar = BuildStratumBar(string.Empty);
            if (sBar != null) _stageHost.Children.Add(sBar);

            Border medallionHost = new Border { VerticalAlignment = VerticalAlignment.Center };
            TextBlock headingTitle = new TextBlock
            {
                FontFamily = SansFont,
                FontSize = 21,
                FontWeight = FontWeights.Bold,
                Foreground = _pal.InkPrimary,
                LineHeight = 27
            };
            TextBlock headingSub = new TextBlock
            {
                FontFamily = SansFont,
                FontSize = 13.5,
                Foreground = _pal.InkBody,
                TextWrapping = TextWrapping.Wrap,
                Margin = new Thickness(0, 3, 0, 0)
            };

            Grid hero = new Grid { Margin = new Thickness(0, 0, 0, 16) };
            hero.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });
            hero.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
            AddCell(hero, 0, medallionHost);

            StackPanel heroTxt = new StackPanel { VerticalAlignment = VerticalAlignment.Center };
            heroTxt.Children.Add(headingTitle);
            heroTxt.Children.Add(headingSub);
            AddCell(hero, 1, heroTxt);
            _stageHost.Children.Add(hero);

            Border ticket = new Border
            {
                CornerRadius = new CornerRadius(6),
                Background = _pal.CardIdleBrush,
                BorderBrush = _pal.BorderCard,
                BorderThickness = new Thickness(2.0),
                Margin = new Thickness(0, 0, 0, 14)
            };
            StackPanel ticketStack = new StackPanel();
            ticketStack.Children.Add(new Border
            {
                Height = 3.0,
                Background = _pal.HorizonBeamBrush
            });
            StackPanel rows = new StackPanel { Margin = new Thickness(16, 12, 16, 12) };
            bool hasAnyRow = false;

            if (_panels.Count > 0)
            {
                int visCount = Math.Min(4, _panels.Count);
                for (int pIdx = 0; pIdx < visCount; pIdx++)
                {
                    if (hasAnyRow) rows.Children.Add(new Border { Height = 1, Background = _pal.BorderSubtle, Margin = new Thickness(0, 9, 0, 9) });
                    hasAnyRow = true;
                    rows.Children.Add(BuildSealPanelRow(_panels[pIdx]));
                }
                if (_panels.Count > 4)
                {
                    if (hasAnyRow) rows.Children.Add(new Border { Height = 1, Background = _pal.BorderSubtle, Margin = new Thickness(0, 9, 0, 9) });
                    hasAnyRow = true;
                    StackPanel moreStack = new StackPanel { Margin = new Thickness(0, 6, 0, 0) };
                    for (int pIdx = 4; pIdx < _panels.Count; pIdx++)
                    {
                        if (pIdx > 4) moreStack.Children.Add(new Border { Height = 1, Background = _pal.BorderSubtle, Margin = new Thickness(0, 7, 0, 7) });
                        moreStack.Children.Add(BuildSealPanelRow(_panels[pIdx]));
                    }
                    rows.Children.Add(new Expander
                    {
                        Header = "+" + (_panels.Count - 4) + " more target contracts",
                        Foreground = _pal.InkMuted,
                        Content = moreStack
                    });
                }
            }

            if (_cards.Count > 0)
            {
                for (int i = 0; i < _cards.Count; i++)
                {
                    if (hasAnyRow) rows.Children.Add(new Border { Height = 1, Background = _pal.BorderSubtle, Margin = new Thickness(0, 9, 0, 9) });
                    hasAnyRow = true;
                    UiCardItem c = _cards[i];
                    string val = c.CardKind == "question" ? (_answers[i] ?? string.Empty) : (_picks[i] ?? string.Empty);
                    string prop = TextSanitizer.SanitizeText(c.ProposedPick);
                    bool modified = (c.CardKind == "question" || (!string.IsNullOrEmpty(prop) && val != prop));

                    StackPanel left = new StackPanel { VerticalAlignment = VerticalAlignment.Center };
                    left.Children.Add(new TextBlock
                    {
                        FontFamily = MonoFont,
                        FontSize = 12,
                        Foreground = _pal.InkMuted,
                        Text = TextSanitizer.SanitizeText(c.ContractId) + " · " + HumanizeSlug(c.CardId)
                    });
                    left.Children.Add(new TextBlock
                    {
                        FontFamily = MonoFont,
                        FontSize = 14,
                        FontWeight = FontWeights.ExtraBold,
                        Foreground = modified ? _pal.Copper : _pal.MintBright,
                        Margin = new Thickness(0, 2, 0, 0),
                        Text = (!string.IsNullOrEmpty(val) ? val : "(unset)") + (modified ? " [updated]" : string.Empty)
                    });

                    int jumpIdx = i;
                    DossierButton editBtn = MakeDossierButton("Edit", "Edit decision " + (i + 1), _pal.BtnBg, _pal.BtnHover, _pal.BorderCard, _pal.InkPrimary, new Thickness(12, 4, 12, 4), false, delegate
                    {
                        _stepIndex = jumpIdx;
                        RearmGuard();
                        RenderAll(true, -1);
                    });
                    editBtn.Control.MinHeight = 30;
                    editBtn.Surface.MinHeight = 30;
                    rows.Children.Add(MakeSplitRow(left, editBtn.Control, new Thickness(0)));
                }
            }

            if (_req.ExecChoices != null && _req.ExecChoices.Count > 0)
            {
                for (int i = 0; i < _req.ExecChoices.Count; i++)
                {
                    UiExecChoiceItem ec = _req.ExecChoices[i];
                    if (ec == null) continue;
                    if (hasAnyRow) rows.Children.Add(new Border { Height = 1, Background = _pal.BorderSubtle, Margin = new Thickness(0, 9, 0, 9) });
                    hasAnyRow = true;
                    StackPanel ecWrap = new StackPanel();
                    string ecCid = TextSanitizer.SanitizeText(ec.ContractId);
                    string ecTitle = (!string.IsNullOrEmpty(ecCid) ? ecCid + " · " : string.Empty) + HumanizeSlug(ec.CardId) + " = " + TextSanitizer.SanitizeText(ec.Pick);
                    List<string> metaParts = new List<string>();
                    string ecEff = TextSanitizer.SanitizeText(ec.Effort);
                    string ecUndo = TextSanitizer.SanitizeText(ec.Undo);
                    if (!string.IsNullOrEmpty(ecEff)) metaParts.Add(ecEff);
                    if (ec.RiskLevel > 0) metaParts.Add("risk " + ec.RiskLevel + "/4");
                    if (!string.IsNullOrEmpty(ecUndo)) metaParts.Add(ecUndo);
                    UIElement rightMeta = metaParts.Count > 0
                        ? (UIElement)new TextBlock { FontFamily = MonoFont, FontSize = 11.5, Foreground = _pal.InkMuted, VerticalAlignment = VerticalAlignment.Center, Text = string.Join(" · ", metaParts.ToArray()) }
                        : null;
                    ecWrap.Children.Add(MakeSplitRow(
                        new TextBlock { FontFamily = MonoFont, FontSize = 12.5, FontWeight = FontWeights.Bold, Foreground = _pal.MintBright, TextWrapping = TextWrapping.Wrap, Text = ecTitle },
                        rightMeta,
                        new Thickness(0)));
                    string ecDoes = TextSanitizer.SanitizeText(ec.Does);
                    if (!string.IsNullOrEmpty(ecDoes))
                    {
                        ecWrap.Children.Add(new TextBlock { FontSize = 13, Foreground = _pal.InkBody, Margin = new Thickness(0, 3, 0, 0), TextWrapping = TextWrapping.Wrap, Text = ecDoes });
                    }
                    string ecAsk = TextSanitizer.SanitizeText(ec.Ask).Trim();
                    string ecWhy = TextSanitizer.SanitizeText(ec.Why).Trim();
                    if (!string.IsNullOrEmpty(ecAsk) || !string.IsNullOrEmpty(ecWhy))
                    {
                        string ratTxt = !string.IsNullOrEmpty(ecAsk) ? (ecAsk + (!string.IsNullOrEmpty(ecWhy) ? " — " + ecWhy : string.Empty)) : ecWhy;
                        ecWrap.Children.Add(new Expander
                        {
                            Header = "Rationale",
                            Foreground = _pal.InkMuted,
                            Margin = new Thickness(0, 3, 0, 0),
                            Content = new TextBlock { FontSize = 12, Foreground = _pal.InkBody, Margin = new Thickness(8, 4, 0, 2), TextWrapping = TextWrapping.Wrap, Text = ratTxt }
                        });
                    }
                    rows.Children.Add(ecWrap);
                }
            }

            if (!hasAnyRow)
            {
                rows.Children.Add(new TextBlock { FontSize = 13.5, Foreground = _pal.InkBody, Text = "All decisions settled in reviewed contracts." });
            }
            ticketStack.Children.Add(rows);

            string shortRef = !string.IsNullOrEmpty(_req.ReviewRef)
                ? ("Snapshot " + (_req.ReviewRef.Length > 32 ? _req.ReviewRef.Substring(0, 32) + "…" : _req.ReviewRef))
                : "Snapshot pending recomputation";
            Border stampBar = new Border
            {
                CornerRadius = new CornerRadius(0, 0, 10, 10),
                Background = _pal.WellBg,
                BorderBrush = _pal.BorderSubtle,
                BorderThickness = new Thickness(0, 1, 0, 0),
                Padding = new Thickness(16, 9, 16, 9),
                Child = MakeSplitRow(
                    new TextBlock { FontFamily = MonoFont, FontSize = 12, Foreground = _pal.Mint, ToolTip = TextSanitizer.SanitizeText(_req.ReviewRef), Text = TextSanitizer.SanitizeText(shortRef) },
                    new TextBlock { FontSize = 12, Foreground = _pal.InkMuted, Text = "Contract snapshot only · Tests run separately" },
                    new Thickness(0))
            };
            ticketStack.Children.Add(stampBar);
            ticket.Child = ticketStack;
            _stageHost.Children.Add(ticket);

            StackPanel ownerSection = new StackPanel { Margin = new Thickness(0, 0, 0, 12) };
            string ownerHint = string.IsNullOrEmpty(_req.Owner) ? "Saved locally after valid approval." : "Applies to this review only.";
            TextBlock ownerLabel = new TextBlock { FontSize = 13, FontWeight = FontWeights.SemiBold, Foreground = _pal.InkPrimary, Margin = new Thickness(0, 0, 0, 5), Text = "Approve as" };
            ownerSection.Children.Add(ownerLabel);
            TextBox ownerBox;
            Border ownerWrap = MakeInputField(out ownerBox, _ownerVal, false);
            AutomationProperties.SetLabeledBy(ownerBox, ownerLabel);
            TextBlock helper = new TextBlock { FontSize = 12, Foreground = _pal.InkMuted, Margin = new Thickness(0, 5, 0, 0), Text = ownerHint };
            WrapPanel approverChips = new WrapPanel { Margin = new Thickness(0, 6, 0, 0), Visibility = Visibility.Collapsed };

            if (_req.PolicyApprovers != null && _req.PolicyApprovers.Count > 0)
            {
                for (int a = 0; a < _req.PolicyApprovers.Count; a++)
                {
                    string apName = TextSanitizer.SanitizeText(_req.PolicyApprovers[a]);
                    DossierButton chip = MakeDossierButton("Use \"" + apName + "\"", "Select policy approver " + apName, _pal.MintSoft, _pal.BtnHover, _pal.MintBorder, _pal.MintBright, new Thickness(10, 3, 10, 3), false, delegate
                    {
                        ownerBox.Text = apName;
                    });
                    chip.Control.MinHeight = 26;
                    chip.Surface.MinHeight = 26;
                    chip.Control.Margin = new Thickness(0, 0, 6, 4);
                    approverChips.Children.Add(chip.Control);
                }
            }

            Action syncOwn = delegate
            {
                _ownerVal = TextSanitizer.SanitizeText((ownerBox.Text ?? string.Empty).Trim());
                bool blank = string.IsNullOrEmpty(_ownerVal);
                bool mismatch = _req.PolicyApprovers != null && _req.PolicyApprovers.Count > 0 && !_req.PolicyApprovers.Contains(_ownerVal);
                helper.Foreground = blank || mismatch ? _pal.Amber : _pal.InkMuted;
                helper.Text = blank ? "Enter the name to record on this approval."
                    : mismatch ? "Select an authorized approver listed in .drift/config.toml:" : ownerHint;
                approverChips.Visibility = mismatch ? Visibility.Visible : Visibility.Collapsed;
                SyncSummaryDynamicState(medallionHost, headingTitle, headingSub, ownerSection);
            };
            syncOwn();
            ownerBox.TextChanged += delegate { syncOwn(); };
            ownerSection.Children.Add(ownerWrap);
            ownerSection.Children.Add(helper);
            ownerSection.Children.Add(approverChips);
            _stageHost.Children.Add(ownerSection);

            StackPanel changeWrap = new StackPanel();
            StackPanel notePanel = new StackPanel { Visibility = _changeRequestOpen ? Visibility.Visible : Visibility.Collapsed, Margin = new Thickness(0, 9, 0, 0) };
            notePanel.Children.Add(new TextBlock { FontSize = 12.5, FontWeight = FontWeights.SemiBold, Foreground = _pal.InkPrimary, Margin = new Thickness(0, 0, 0, 3), Text = "Instructions for the agent" });
            notePanel.Children.Add(new TextBlock { FontSize = 12, Foreground = _pal.InkMuted, Margin = new Thickness(0, 0, 0, 6), Text = "Sending instructions requests an updated candidate. Zero contracts will be approved." });
            TextBox noteBox;
            Border noteField = MakeInputField(out noteBox, _noteVal, true);
            noteBox.TextChanged += delegate
            {
                _noteVal = noteBox.Text ?? string.Empty;
                RenderSpine();
                SyncSummaryDynamicState(medallionHost, headingTitle, headingSub, ownerSection);
            };
            notePanel.Children.Add(noteField);

            DossierButton toggleChangeBtn = null;
            toggleChangeBtn = MakeDossierButton(
                _changeRequestOpen ? "Cancel change request" : "Request a change…",
                "Request a change from the agent",
                _pal.BtnBg,
                _pal.BtnHover,
                _pal.BorderCard,
                _pal.InkPrimary,
                new Thickness(13, 6, 13, 6),
                false,
                delegate
                {
                    _changeRequestOpen = !_changeRequestOpen;
                    if (!_changeRequestOpen) _noteVal = string.Empty;
                    notePanel.Visibility = _changeRequestOpen ? Visibility.Visible : Visibility.Collapsed;
                    toggleChangeBtn.Label.Text = _changeRequestOpen ? "Cancel change request" : "Request a change…";
                    toggleChangeBtn.SyncVisual(false, false);
                    if (_changeRequestOpen) noteBox.Focus();
                    RenderSpine();
                    SyncSummaryDynamicState(medallionHost, headingTitle, headingSub, ownerSection);
                });
            toggleChangeBtn.Control.HorizontalAlignment = HorizontalAlignment.Left;
            changeWrap.Children.Add(toggleChangeBtn.Control);
            changeWrap.Children.Add(notePanel);
            _stageHost.Children.Add(changeWrap);

            SyncSummaryDynamicState(medallionHost, headingTitle, headingSub, ownerSection);
        }

        private void SyncSummaryDynamicState(Border medallionHost, TextBlock headingTitle, TextBlock headingSub, StackPanel ownerSection)
        {
            bool amend = HasAmendments() || !_req.CanSealDirectly || string.IsNullOrEmpty(_req.ReviewRef);
            medallionHost.Child = BuildSealMedallion(amend);
            int nTargs = _req.TargetsCount > 0 ? _req.TargetsCount : 1;
            if (amend)
            {
                headingTitle.Text = "Changes requested";
                headingSub.Text = "DRIFT will return your updated choices or instructions for delta recomputation. Zero contracts will be approved.";
                ownerSection.Visibility = Visibility.Collapsed;
            }
            else
            {
                headingTitle.Text = "Ready to approve " + nTargs + (nTargs == 1 ? " contract" : " contracts");
                headingSub.Text = "Press Ctrl+Enter or click Approve below to seal this verified snapshot.";
                ownerSection.Visibility = Visibility.Visible;
            }
            SyncFooterState();
        }

        private void SyncStatusHeader(bool animateBeam)
        {
            if (_specMode)
            {
                _stageStatusText.Text = "Specification & baseline delta";
                return;
            }
            string ed = TextSanitizer.SanitizeText(_req.Edition);
            _stageStatusText.Text = "Step " + (_stepIndex + 1) + " of " + TotalSteps() + (!string.IsNullOrEmpty(ed) ? ("  ·  DRIFT " + ed) : string.Empty);

            if (_horizonScale != null)
            {
                double prev = _horizonScale.ScaleX;
                double ratio = TotalSteps() <= 1 ? 1.0 : (double)(_stepIndex + 1) / (double)TotalSteps();
                if (animateBeam && AllowMotion())
                {
                    _horizonScale.BeginAnimation(ScaleTransform.ScaleXProperty, new DoubleAnimation(prev, ratio, new Duration(TimeSpan.FromMilliseconds(240)))
                    {
                        EasingFunction = new CubicEase { EasingMode = EasingMode.EaseOut }
                    });
                }
                else
                {
                    _horizonScale.BeginAnimation(ScaleTransform.ScaleXProperty, null);
                    _horizonScale.ScaleX = ratio;
                }
            }
        }

        private void RenderCurrentStep(bool animateCascade, int slideDir)
        {
            _stageHost.Children.Clear();
            _optionHandles.Clear();
            _stageScroll.ScrollToTop();
            SyncStatusHeader(animateCascade);

            if (_stepIndex < _cards.Count) RenderDecisionStep(_stepIndex, _cards[_stepIndex]);
            else RenderSummaryStep();

            if (_specMode) RefreshSpecContextStrip();
            if (animateCascade && AllowMotion())
            {
                AnimateSlideFade(_stageHost, _stageSlide, slideDir * 12.0, 0.0, 190);
                for (int i = 0; i < _stageHost.Children.Count; i++)
                {
                    AnimateCascadeItem(_stageHost.Children[i], i);
                }
            }
            SyncFooterState();
        }

        private void RenderAll(bool animateCascade, int slideDir)
        {
            RenderSpine();
            RenderCurrentStep(animateCascade, slideDir);
        }

        private void Navigate(int delta)
        {
            int next = _stepIndex + delta;
            if (next < 0 || next >= TotalSteps()) return;
            if (delta > 0 && _stepIndex < _cards.Count && !CurrentStepReady()) return;
            if (delta > 0 && _stepIndex < _cards.Count) _reviewedSteps.Add(_stepIndex);
            _stepIndex = next;
            RearmGuard();
            RenderAll(true, delta > 0 ? 1 : -1);
        }

        private void SyncFooterState()
        {
            if (_submitting) return;

            if (_specMode)
            {
                _backButton.Control.Visibility = Visibility.Collapsed;
                SetButtonIcons(_primaryButton, BuildCtaSocket("back", false), "Back to decision", null, 9);
                _primaryButton.NormalBg = _pal.CopperCtaBrush;
                _primaryButton.HoverBg = _pal.CopperCtaHoverBrush;
                _primaryButton.NormalBorder = _pal.OuterRimBrush;
                _primaryButton.FocusBorder = _pal.SpineMintBright;
                _primaryButton.NormalFg = _pal.OnCopper;
                _primaryButton.IsEnabledState = true;
                _primaryButton.IsArmedVisual = true;
                _primaryButton.SyncVisual(false, false);
                return;
            }

            _backButton.Control.Visibility = Visibility.Visible;
            _backButton.IsEnabledState = _stepIndex > 0;
            SetButtonIcons(_backButton, BuildUiIcon("arrow-left", _pal.InkBody, 12.5), "Back", null, 6);
            _backButton.SyncVisual(false, false);

            bool onSummary = _stepIndex >= _cards.Count;
            bool stepReady = CurrentStepReady();
            _primaryButton.IsEnabledState = _armed && stepReady;
            _primaryButton.IsArmedVisual = _armed;

            if (!onSummary)
            {
                bool toSeal = (_stepIndex + 1 == _cards.Count);
                string nextText = toSeal ? "Review & Seal" : "Continue";
                SetButtonIcons(_primaryButton, null, nextText, BuildCtaSocket(toSeal ? "seal-next" : "next", false), 10);
                _primaryButton.NormalBg = _pal.CopperCtaBrush;
                _primaryButton.HoverBg = _pal.CopperCtaHoverBrush;
                _primaryButton.NormalBorder = _pal.OuterRimBrush;
                _primaryButton.FocusBorder = _pal.SpineMintBright;
                _primaryButton.NormalFg = _pal.OnCopper;
                _primaryButton.SyncVisual(false, false);
                return;
            }

            bool amend = HasAmendments() || !_req.CanSealDirectly || string.IsNullOrEmpty(_req.ReviewRef);
            int nTargs = _req.TargetsCount > 0 ? _req.TargetsCount : 1;
            if (amend)
            {
                SetButtonIcons(_primaryButton, BuildCtaSocket("amend", false), "Send for re-review  Ctrl+Enter", null, 9);
                _primaryButton.NormalBg = _pal.CopperCtaBrush;
                _primaryButton.HoverBg = _pal.CopperCtaHoverBrush;
                _primaryButton.NormalBorder = _pal.OuterRimBrush;
                _primaryButton.FocusBorder = _pal.SpineMintBright;
                _primaryButton.NormalFg = _pal.OnCopper;
            }
            else
            {
                SetButtonIcons(_primaryButton, BuildCtaSocket("approve", true), "Approve " + nTargs + (nTargs == 1 ? " contract" : " contracts") + "  Ctrl+Enter", null, 9);
                _primaryButton.NormalBg = _pal.MintCtaBrush;
                _primaryButton.HoverBg = _pal.MintCtaHoverBrush;
                _primaryButton.NormalBorder = _pal.OuterRimBrush;
                _primaryButton.FocusBorder = _pal.SpineMintBright;
                _primaryButton.NormalFg = _pal.OnMint;
            }
            _primaryButton.SyncVisual(false, false);
        }

        private void OnPrimaryAction(bool allowFinalCommit)
        {
            if (_submitting || !_armed || !CurrentStepReady()) return;
            if (_stepIndex < _cards.Count)
            {
                Navigate(1);
                return;
            }
            if (!allowFinalCommit) return;

            _submitting = true;
            List<UiSelectionItem> sels = new List<UiSelectionItem>();
            for (int i = 0; i < _cards.Count; i++)
            {
                UiCardItem c = _cards[i];
                sels.Add(new UiSelectionItem
                {
                    ContractId = TextSanitizer.SanitizeText(c.ContractId),
                    CardKind = TextSanitizer.SanitizeText(c.CardKind),
                    CardId = TextSanitizer.SanitizeText(c.CardId),
                    SelectedPick = TextSanitizer.SanitizeText(_picks[i]),
                    Answer = TextSanitizer.SanitizeText(_answers[i])
                });
            }

            bool amend = HasAmendments() || !_req.CanSealDirectly || string.IsNullOrEmpty(_req.ReviewRef);
            string finalNote = (_changeRequestOpen && !string.IsNullOrEmpty(_noteVal)) ? TextSanitizer.SanitizeText(_noteVal.Trim()) : string.Empty;
            ResultGesture = new UiGestureEnvelope
            {
                Schema = "drift.ui-gesture/1",
                RequestId = TextSanitizer.SanitizeText(_req.RequestId),
                Action = amend ? "amend" : "approve",
                ConfirmedReviewRef = amend ? string.Empty : TextSanitizer.SanitizeText(_req.ReviewRef),
                ConfirmedOwner = TextSanitizer.SanitizeText((_ownerVal ?? string.Empty).Trim()),
                Note = finalNote,
                Selections = sels
            };

            _primaryButton.Label.Text = amend ? "Sending..." : "Sealing snapshot...";
            _primaryButton.IsEnabledState = false;
            _primaryButton.SyncVisual(false, false);

            if (!amend && AllowMotion() && _shockwavePrimary != null && _shockScale1 != null)
            {
                QuarticEase qe = new QuarticEase { EasingMode = EasingMode.EaseOut };
                Duration d1 = new Duration(TimeSpan.FromMilliseconds(220));
                _shockwavePrimary.BeginAnimation(UIElement.OpacityProperty, new DoubleAnimation(0.95, 0.0, d1) { EasingFunction = qe });
                _shockScale1.BeginAnimation(ScaleTransform.ScaleXProperty, new DoubleAnimation(0.7, 1.9, d1) { EasingFunction = qe });
                _shockScale1.BeginAnimation(ScaleTransform.ScaleYProperty, new DoubleAnimation(0.7, 1.9, d1) { EasingFunction = qe });

                if (_shockwaveSecondary != null && _shockScale2 != null)
                {
                    _shockwaveSecondary.BeginAnimation(UIElement.OpacityProperty, new DoubleAnimation(0.75, 0.0, d1) { BeginTime = TimeSpan.FromMilliseconds(40), EasingFunction = qe });
                    _shockScale2.BeginAnimation(ScaleTransform.ScaleXProperty, new DoubleAnimation(0.7, 1.65, d1) { BeginTime = TimeSpan.FromMilliseconds(40), EasingFunction = qe });
                    _shockScale2.BeginAnimation(ScaleTransform.ScaleYProperty, new DoubleAnimation(0.7, 1.65, d1) { BeginTime = TimeSpan.FromMilliseconds(40), EasingFunction = qe });
                }

                DispatcherTimer closeDelay = new DispatcherTimer { Interval = TimeSpan.FromMilliseconds(225) };
                closeDelay.Tick += delegate { closeDelay.Stop(); Close(); };
                closeDelay.Start();
                return;
            }
            Close();
        }

        private void OnWindowPreviewKeyDown(object sender, KeyEventArgs e)
        {
            _idleClock.Restart();

            if (e.Key == Key.Escape)
            {
                e.Handled = true;
                if (e.IsRepeat) return;
                if (_morePopup != null && _morePopup.IsOpen)
                {
                    _morePopup.IsOpen = false;
                    _moreButton.Control.Focus();
                    return;
                }
                if (_specMode) { SetSpecMode(false); return; }
                if (_armed) Close();
                return;
            }

            if (e.Key == Key.Enter && (Keyboard.Modifiers & ModifierKeys.Control) == ModifierKeys.Control)
            {
                e.Handled = true;
                if (e.IsRepeat || !_armed) return;
                if (_specMode) SetSpecMode(false);
                if (_stepIndex < _cards.Count)
                {
                    if (AllCardsReady())
                    {
                        for (int k = 0; k < _cards.Count; k++) _reviewedSteps.Add(k);
                        _stepIndex = _cards.Count;
                        RearmGuard();
                        RenderAll(true, 1);
                    }
                    return;
                }
                OnPrimaryAction(true);
                return;
            }

            if (Keyboard.FocusedElement is TextBox) return;

            if (e.Key == Key.Enter || e.Key == Key.Space)
            {
                ToggleButton header = Keyboard.FocusedElement as ToggleButton;
                Expander disclosure = header != null ? header.TemplatedParent as Expander : Keyboard.FocusedElement as Expander;
                if (disclosure != null)
                {
                    e.Handled = true;
                    if (!e.IsRepeat) disclosure.IsExpanded = !disclosure.IsExpanded;
                    return;
                }
            }

            if (e.IsRepeat)
            {
                e.Handled = true;
                return;
            }
            if (!_armed)
            {
                _armTimer.Stop();
                _armTimer.Start();
                e.Handled = true;
                return;
            }

            if (Keyboard.FocusedElement is Button && (e.Key == Key.Enter || e.Key == Key.Space)) return;

            if (_specMode && (e.Key == Key.Left || e.Key == Key.Right))
            {
                e.Handled = true;
                int nextTab = e.Key == Key.Left ? ((_activeTabIndex + 2) % 3) : ((_activeTabIndex + 1) % 3);
                SelectSpecTab(nextTab, true);
                return;
            }

            if (e.Key == Key.Space && !(Keyboard.FocusedElement is RadioButton))
            {
                e.Handled = true;
                ToggleSpecMode();
                return;
            }
            if (_specMode)
            {
                if (e.Key == Key.Up && _specScroll != null) { e.Handled = true; _specScroll.ScrollToVerticalOffset(Math.Max(0.0, _specScroll.VerticalOffset - 48.0)); }
                else if (e.Key == Key.Down && _specScroll != null) { e.Handled = true; _specScroll.ScrollToVerticalOffset(Math.Min(_specScroll.ScrollableHeight, _specScroll.VerticalOffset + 48.0)); }
                return;
            }
            if (e.Key == Key.Left) { e.Handled = true; Navigate(-1); return; }
            if (e.Key == Key.Right) { e.Handled = true; Navigate(1); return; }

            int digitIdx = -1;
            if (e.Key >= Key.D1 && e.Key <= Key.D9) digitIdx = (int)(e.Key - Key.D1);
            else if (e.Key >= Key.NumPad1 && e.Key <= Key.NumPad9) digitIdx = (int)(e.Key - Key.NumPad1);

            if (_stepIndex < _cards.Count && digitIdx >= 0 && Keyboard.Modifiers == ModifierKeys.None)
            {
                UiCardItem cur = _cards[_stepIndex];
                if (cur.Options != null && digitIdx < cur.Options.Count)
                {
                    e.Handled = true;
                    ApplySelectionInPlace(_stepIndex, TextSanitizer.SanitizeText(cur.Options[digitIdx].Id));
                }
                return;
            }

            if (e.Key == Key.Enter && _stepIndex < _cards.Count)
            {
                e.Handled = true;
                Navigate(1);
            }
        }
    }

    public static class Program
    {
        private static UiRequestEnvelope ReadRequest(string path)
        {
            byte[] raw = File.ReadAllBytes(path);
            DataContractJsonSerializer ser = new DataContractJsonSerializer(typeof(UiRequestEnvelope));
            using (MemoryStream ms = new MemoryStream(raw))
            {
                return (UiRequestEnvelope)ser.ReadObject(ms);
            }
        }

        private static void WriteGesture(string path, UiGestureEnvelope env)
        {
            DataContractJsonSerializer ser = new DataContractJsonSerializer(typeof(UiGestureEnvelope));
            using (MemoryStream ms = new MemoryStream())
            {
                ser.WriteObject(ms, env);
                string tmp = path + ".tmp";
                File.WriteAllBytes(tmp, ms.ToArray());
                if (File.Exists(path)) File.Delete(path);
                File.Move(tmp, path);
            }
        }

        [STAThread]
        public static int Main(string[] args)
        {
            try
            {
                if (args.Length == 1 && args[0] == "--probe")
                {
                    string reason;
                    bool ok = NativeWin32.ProbeInteractiveDesktop(out reason);
                    Console.WriteLine("{\"desktop_ok\":" + (ok ? "true" : "false") + ",\"reason\":\"" + TextSanitizer.SanitizeText(reason) + "\"}");
                    return ok ? 0 : 10;
                }

                if (args.Length == 3 && args[0] == "--self-test")
                {
                    UiRequestEnvelope sreq = ReadRequest(args[1]);
                    if (sreq == null || sreq.Schema != "drift.ui-request/1") return 2;
                    DecisionWindow probeWin = new DecisionWindow(sreq);
                    probeWin.Close();
                    string cleaned = TextSanitizer.SanitizeText(sreq.KernelBanner + "\u202E\u0007");
                    UiGestureEnvelope g = new UiGestureEnvelope
                    {
                        Schema = "drift.ui-gesture/1",
                        RequestId = TextSanitizer.SanitizeText(sreq.RequestId),
                        Action = "self_test_ok",
                        ConfirmedReviewRef = TextSanitizer.SanitizeText(sreq.ReviewRef),
                        ConfirmedOwner = TextSanitizer.SanitizeText(sreq.Owner),
                        Note = cleaned,
                        Selections = new List<UiSelectionItem>()
                    };
                    WriteGesture(args[2], g);
                    return 0;
                }

                if (args.Length != 2) return 2;
                UiRequestEnvelope req = ReadRequest(args[0]);
                if (req == null || req.Schema != "drift.ui-request/1") return 2;

                string reqId = TextSanitizer.SanitizeText(req.RequestId);
                bool createdReq;
                using (Mutex reqMutex = new Mutex(true, "Local\\DriftUi_Req_" + reqId, out createdReq))
                {
                    if (!createdReq) return 3;
                    using (Mutex queueMutex = new Mutex(false, "Local\\DriftUi_GlobalQueue"))
                    {
                        bool locked = false;
                        try
                        {
                            try { locked = queueMutex.WaitOne(TimeSpan.FromSeconds(15)); }
                            catch (AbandonedMutexException) { locked = true; }
                            if (!locked) return 3;

                            Application app = new Application();
                            DecisionWindow win = new DecisionWindow(req);
                            app.Run(win);
                            WriteGesture(args[1], win.ResultGesture);
                            return 0;
                        }
                        finally
                        {
                            if (locked)
                            {
                                try { queueMutex.ReleaseMutex(); } catch { }
                            }
                        }
                    }
                }
            }
            catch (Exception ex)
            {
                try { Console.Error.WriteLine("drift-ui-win: " + ex.Message); } catch { }
                return 2;
            }
        }
    }
}
