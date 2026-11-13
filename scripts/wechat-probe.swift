import Foundation
import AppKit
import ApplicationServices
let apps=NSWorkspace.shared.runningApplications.filter{$0.bundleIdentifier == "com.tencent.xinWeChat"}
let trusted=AXIsProcessTrusted()
var report:[String:Any] = ["accessibilityTrusted":trusted,"wechatRunning":!apps.isEmpty,"os":ProcessInfo.processInfo.operatingSystemVersionString]
if trusted, let app=apps.first {
 let ax=AXUIElementCreateApplication(app.processIdentifier)
 var value:CFTypeRef?
 let status=AXUIElementCopyAttributeValue(ax,kAXWindowsAttribute as CFString,&value)
 report["windowQueryStatus"]=status.rawValue
 if let windows=value as? [AXUIElement] {
  report["windowCount"]=windows.count
  var roles:[String:Int]=[:];var visited=0
  func walk(_ item:AXUIElement,_ depth:Int){
   if depth>12 || visited>=1500{return};visited+=1
   var r:CFTypeRef?;AXUIElementCopyAttributeValue(item,kAXRoleAttribute as CFString,&r)
   if let name=r as? String{roles[name,default:0]+=1}
   var child:CFTypeRef?;AXUIElementCopyAttributeValue(item,kAXChildrenAttribute as CFString,&child)
   for c in (child as? [AXUIElement]) ?? []{walk(c,depth+1)}
  }
  for w in windows{walk(w,0)}
  report["roleCounts"]=roles;report["inspectedElements"]=visited
 }
}
print(String(data:try! JSONSerialization.data(withJSONObject:report,options:[.sortedKeys]),encoding:.utf8)!)
