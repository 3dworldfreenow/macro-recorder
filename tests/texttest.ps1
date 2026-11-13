# Test window with known text; writes label centers (screen coords) to texttest_pos.txt
Add-Type -AssemblyName System.Windows.Forms, System.Drawing
Add-Type @"
using System; using System.Runtime.InteropServices;
public class D { [DllImport("user32.dll")] public static extern bool SetProcessDPIAware(); }
"@
[D]::SetProcessDPIAware() | Out-Null
$f = New-Object Windows.Forms.Form
$f.Text = "TextTest"; $f.Width = 460; $f.Height = 260
$f.StartPosition = "Manual"; $f.Left = 540; $f.Top = 330; $f.BackColor = "White"
function L($text, $top) {
  $l = New-Object Windows.Forms.Label
  $l.Text = $text; $l.AutoSize = $true; $l.Left = 30; $l.Top = $top
  $l.Font = New-Object Drawing.Font("Segoe UI", 22)
  $f.Controls.Add($l); return $l
}
$a = L "Score: 42" 20
$b = L "Status: READY" 100
$f.Add_Shown({
  $pa = $a.PointToScreen([Drawing.Point]::new([int]($a.Width/2), [int]($a.Height/2)))
  $pb = $b.PointToScreen([Drawing.Point]::new([int]($b.Width/2), [int]($b.Height/2)))
  Set-Content texttest_pos.txt ("{0} {1} {2} {3}" -f $pa.X, $pa.Y, $pb.X, $pb.Y)
})
[void]$f.ShowDialog()
