# Test window: Back + two "Accept" buttons (next to Mary / John). Logs clicks.
Add-Type -AssemblyName System.Windows.Forms, System.Drawing
Add-Type @"
using System; using System.Runtime.InteropServices;
public class D2 { [DllImport("user32.dll")] public static extern bool SetProcessDPIAware(); }
"@
[D2]::SetProcessDPIAware() | Out-Null
$f = New-Object Windows.Forms.Form
$f.Text = "FindTest"; $f.Width = 460; $f.Height = 300; $f.BackColor = "White"
$f.StartPosition = "Manual"; $f.Left = 300; $f.Top = 250
$font = New-Object Drawing.Font("Segoe UI", 16)
function B($text, $tag, $x, $y) {
  $b = New-Object Windows.Forms.Button
  $b.Text = $text; $b.Tag = $tag; $b.Left = $x; $b.Top = $y; $b.Width = 150; $b.Height = 44
  $b.Font = $font
  $b.Add_Click({ param($s, $e) Add-Content "$pwd\findtest_clicks.txt" $s.Tag })
  $f.Controls.Add($b)
}
function L($text, $x, $y) {
  $l = New-Object Windows.Forms.Label
  $l.Text = $text; $l.Left = $x; $l.Top = $y; $l.AutoSize = $true; $l.Font = $font
  $f.Controls.Add($l)
}
B "Back" "Back" 20 15
L "Mary" 30 100; B "Accept" "MaryAccept" 220 92
L "John" 30 170; B "Accept" "JohnAccept" 220 162
$f.Add_Shown({
  Set-Content "$pwd\findtest_pos.txt" ("{0} {1}" -f ($f.Left + [int]($f.Width/2)), ($f.Top + [int]($f.Height/2)))
})
[void]$f.ShowDialog()
